import logging
import sys

import torch
import torch.nn.functional as F
from mmdet.core import (bbox2roi, bbox_mapping, merge_aug_bboxes,
                        merge_aug_masks, merge_aug_proposals, multiclass_nms)

logger = logging.getLogger(__name__)

if sys.version_info >= (3, 7):
    from mmdet.utils.contextmanagers import completed


class RPNTestMixin(object):
    if sys.version_info >= (3, 7):
        async def async_test_rpn(self, x, img_meta, rpn_test_cfg):
            sleep_interval = rpn_test_cfg.pop('async_sleep_interval', 0.025)
            async with completed(
                    __name__, 'rpn_head_forward',
                    sleep_interval=sleep_interval):
                rpn_outs = self.rpn_head(x)

            proposal_inputs = rpn_outs + (img_meta, rpn_test_cfg)

            proposal_list = self.rpn_head.get_bboxes(*proposal_inputs)
            return proposal_list

    def simple_test_rpn(self, x, img_meta, rpn_test_cfg):
        rpn_outs = self.rpn_head(x)
        proposal_inputs = rpn_outs + (img_meta, rpn_test_cfg)
        proposal_list = self.rpn_head.get_bboxes(*proposal_inputs)
        return proposal_list

    def aug_test_rpn(self, feats, img_metas, rpn_test_cfg):
        imgs_per_gpu = len(img_metas[0])
        aug_proposals = [[] for _ in range(imgs_per_gpu)]
        for x, img_meta in zip(feats, img_metas):
            proposal_list = self.simple_test_rpn(x, img_meta, rpn_test_cfg)
            for i, proposals in enumerate(proposal_list):
                aug_proposals[i].append(proposals)
        # reorganize the order of 'img_metas' to match the dimensions
        # of 'aug_proposals'
        aug_img_metas = []
        for i in range(imgs_per_gpu):
            aug_img_meta = []
            for j in range(len(img_metas)):
                aug_img_meta.append(img_metas[j][i])
            aug_img_metas.append(aug_img_meta)
        # after merging, proposals will be rescaled to the original image size
        merged_proposals = [
            merge_aug_proposals(proposals, aug_img_meta, rpn_test_cfg)
            for proposals, aug_img_meta in zip(aug_proposals, aug_img_metas)
        ]
        return merged_proposals


class BBoxTestMixin(object):
    if sys.version_info >= (3, 7):

        async def async_test_bboxes(self,
                                    x,
                                    img_meta,
                                    proposals,
                                    rcnn_test_cfg,
                                    rescale=False,
                                    bbox_semaphore=None,
                                    global_lock=None):
            """Async test only det bboxes without augmentation."""
            rois = bbox2roi(proposals)
            roi_feats = self.bbox_roi_extractor(
                x[:len(self.bbox_roi_extractor.featmap_strides)], rois)
            if self.with_shared_head:
                roi_feats = self.shared_head(roi_feats)
            sleep_interval = rcnn_test_cfg.get('async_sleep_interval', 0.017)

            async with completed(
                    __name__, 'bbox_head_forward',
                    sleep_interval=sleep_interval):
                cls_score, bbox_pred = self.bbox_head(roi_feats)

            img_shape = img_meta[0]['img_shape']
            scale_factor = img_meta[0]['scale_factor']
            det_bboxes, det_labels = self.bbox_head.get_det_bboxes(
                rois,
                cls_score,
                bbox_pred,
                img_shape,
                scale_factor,
                rescale=rescale,
                cfg=rcnn_test_cfg)

            return det_bboxes, det_labels

    def simple_test_bboxes(self,
                           x,
                           img_meta,
                           proposals,
                           rcnn_test_cfg,
                           rescale=False,
                           return_dist=False):
        """Test only det bboxes without augmentation."""
        rois = bbox2roi(proposals)
        roi_feats = self.bbox_roi_extractor(
            x[:len(self.bbox_roi_extractor.featmap_strides)], rois)
        if self.with_shared_head:
            roi_feats = self.shared_head(roi_feats)
        cls_score, bbox_pred = self.bbox_head(roi_feats)
        img_shape = img_meta[0]['img_shape']
        scale_factor = img_meta[0]['scale_factor']
        det_result = self.bbox_head.get_det_bboxes(
            rois,
            cls_score,
            bbox_pred,
            img_shape,
            scale_factor,
            rescale=rescale,
            cfg=rcnn_test_cfg,
            return_dist=return_dist)
        return det_result

    def simple_test_given_bboxes(self,
                                 x,
                                 proposals):
        """For SGG~SGCLS mode: Given gt boxes, extract its predicted scores and score dists.
            Witout any post-process.
        """
        rois = bbox2roi(proposals)
        roi_feats = self.bbox_roi_extractor(
            x[:len(self.bbox_roi_extractor.featmap_strides)], rois)
        if self.with_shared_head:
            roi_feats = self.shared_head(roi_feats)
        cls_score, _ = self.bbox_head(roi_feats)
        cls_score[:, 1:] = F.softmax(cls_score[:, 1:], dim=1)
        _, labels = torch.max(cls_score[:, 1:], dim=1)
        labels += 1
        cls_score[:, 0] = 0
        return labels, cls_score

    def aug_test_bboxes(self, feats, img_metas, proposal_list, rcnn_test_cfg):
        aug_bboxes = []
        aug_scores = []
        for x, img_meta in zip(feats, img_metas):
            # only one image in the batch
            img_shape = img_meta[0]['img_shape']
            scale_factor = img_meta[0]['scale_factor']
            flip = img_meta[0]['flip']
            # TODO more flexible
            proposals = bbox_mapping(proposal_list[0][:, :4], img_shape,
                                     scale_factor, flip)
            rois = bbox2roi([proposals])
            # recompute feature maps to save GPU memory
            roi_feats = self.bbox_roi_extractor(
                x[:len(self.bbox_roi_extractor.featmap_strides)], rois)
            if self.with_shared_head:
                roi_feats = self.shared_head(roi_feats)
            cls_score, bbox_pred = self.bbox_head(roi_feats)
            bboxes, scores = self.bbox_head.get_det_bboxes(
                rois,
                cls_score,
                bbox_pred,
                img_shape,
                scale_factor,
                rescale=False,
                cfg=None)
            aug_bboxes.append(bboxes)
            aug_scores.append(scores)
        # after merging, bboxes will be rescaled to the original image size
        merged_bboxes, merged_scores = merge_aug_bboxes(
            aug_bboxes, aug_scores, img_metas, rcnn_test_cfg)
        det_bboxes, det_labels = multiclass_nms(merged_bboxes, merged_scores,
                                                rcnn_test_cfg.score_thr,
                                                rcnn_test_cfg.nms,
                                                rcnn_test_cfg.max_per_img)
        return det_bboxes, det_labels


class MaskTestMixin(object):
    if sys.version_info >= (3, 7):

        async def async_test_mask(self,
                                  x,
                                  img_meta,
                                  det_bboxes,
                                  det_labels,
                                  rescale=False,
                                  mask_test_cfg=None,
                                  det_weight=None):
            # image shape of the first image in the batch (only one)
            ori_shape = img_meta[0]['ori_shape']
            scale_factor = img_meta[0]['scale_factor']
            if det_bboxes.shape[0] == 0:
                segm_result = [[]
                               for _ in range(self.mask_head.num_classes - 1)]
            else:
                _bboxes = (
                    det_bboxes[:, :4] *
                    scale_factor if rescale else det_bboxes)
                mask_rois = bbox2roi([_bboxes])
                mask_feats = self.mask_roi_extractor(
                    x[:len(self.mask_roi_extractor.featmap_strides)],
                    mask_rois)

                if self.with_shared_head:
                    mask_feats = self.shared_head(mask_feats)
                if mask_test_cfg and mask_test_cfg.get('async_sleep_interval'):
                    sleep_interval = mask_test_cfg['async_sleep_interval']
                else:
                    sleep_interval = 0.035
                async with completed(
                        __name__,
                        'mask_head_forward',
                        sleep_interval=sleep_interval):
                    if self.mask_head.__class__.__name__ == 'TransferMaskHead':
                        assert det_weight is not None
                        mask_inputs = (mask_feats, det_weight)
                    else:
                        mask_inputs = (mask_feats,)
                    mask_pred = self.mask_head(*mask_inputs)
                segm_result = self.mask_head.get_seg_masks(
                    mask_pred, _bboxes, det_labels, self.test_cfg.rcnn,
                    ori_shape, scale_factor, rescale)
            return segm_result

    def simple_test_mask(self,
                         x,
                         img_meta,
                         det_bboxes,
                         det_labels,
                         rescale=False,
                         det_weight=None,
                         with_point=False):
        # image shape of the first image in the batch (only one)
        ori_shape = img_meta[0]['ori_shape']
        scale_factor = img_meta[0]['scale_factor']
        if det_bboxes.shape[0] == 0:
            segm_result = [[] for _ in range(self.mask_head.num_classes - 1)]
            if with_point:
                point_result = [[] for _ in range(self.mask_head.num_classes - 1)]
                return segm_result, point_result
            else:
                return segm_result
        else:
            # if det_bboxes is rescaled to the original image size, we need to
            # rescale it back to the testing scale to obtain RoIs.
            if rescale and not isinstance(scale_factor, float):
                scale_factor = torch.from_numpy(scale_factor).to(
                    det_bboxes.device)
            _bboxes = (
                det_bboxes[:, :4] * scale_factor if rescale else det_bboxes)
            mask_rois = bbox2roi([_bboxes])
            mask_feats = self.mask_roi_extractor(
                x[:len(self.mask_roi_extractor.featmap_strides)], mask_rois)
            if self.with_shared_head:
                mask_feats = self.shared_head(mask_feats)
            if self.mask_head.__class__.__name__ == 'TransferMaskHead':
                assert det_weight is not None
                mask_inputs = (mask_feats, det_weight)
            else:
                mask_inputs = (mask_feats,)
            mask_pred = self.mask_head(*mask_inputs)
            result = self.mask_head.get_seg_masks(mask_pred, _bboxes,
                                                  det_labels,
                                                  self.test_cfg.rcnn,
                                                  ori_shape, scale_factor,
                                                  rescale,
                                                  with_point)
            return result

    def aug_test_mask(self, feats, img_metas, det_bboxes, det_labels, det_weight=None):
        if det_bboxes.shape[0] == 0:
            segm_result = [[] for _ in range(self.mask_head.num_classes - 1)]
        else:
            aug_masks = []
            for x, img_meta in zip(feats, img_metas):
                img_shape = img_meta[0]['img_shape']
                scale_factor = img_meta[0]['scale_factor']
                flip = img_meta[0]['flip']
                _bboxes = bbox_mapping(det_bboxes[:, :4], img_shape,
                                       scale_factor, flip)
                mask_rois = bbox2roi([_bboxes])
                mask_feats = self.mask_roi_extractor(
                    x[:len(self.mask_roi_extractor.featmap_strides)],
                    mask_rois)
                if self.with_shared_head:
                    mask_feats = self.shared_head(mask_feats)
                if self.mask_head.__class__.__name__ == 'TransferMaskHead':
                    assert det_weight is not None
                    mask_inputs = (mask_feats, det_weight)
                else:
                    mask_inputs = (mask_feats,)
                mask_pred = self.mask_head(*mask_inputs)
                # convert to numpy array to save memory
                aug_masks.append(mask_pred.sigmoid().cpu().numpy())
            merged_masks = merge_aug_masks(aug_masks, img_metas,
                                           self.test_cfg.rcnn)

            ori_shape = img_metas[0][0]['ori_shape']
            segm_result = self.mask_head.get_seg_masks(
                merged_masks,
                det_bboxes,
                det_labels,
                self.test_cfg.rcnn,
                ori_shape,
                scale_factor=1.0,
                rescale=False)
        return segm_result
