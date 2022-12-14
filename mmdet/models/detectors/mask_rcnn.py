from ..registry import DETECTORS
from .two_stage import TwoStageDetector


@DETECTORS.register_module
class MaskRCNN(TwoStageDetector):

    def __init__(self,
                 backbone,
                 rpn_head,
                 bbox_roi_extractor,
                 bbox_head,
                 mask_roi_extractor,
                 mask_head,
                 train_cfg,
                 test_cfg,
                 neck=None,
                 shared_head=None,
                 relation_head=None,
                 saliency_detector=None,
                 pretrained=None,
                 with_point=False):
        super(MaskRCNN, self).__init__(
            backbone=backbone,
            neck=neck,
            shared_head=shared_head,
            rpn_head=rpn_head,
            bbox_roi_extractor=bbox_roi_extractor,
            bbox_head=bbox_head,
            mask_roi_extractor=mask_roi_extractor,
            mask_head=mask_head,
            relation_head=relation_head,
            saliency_detector=saliency_detector,
            train_cfg=train_cfg,
            test_cfg=test_cfg,
            pretrained=pretrained,
            with_point=with_point)
