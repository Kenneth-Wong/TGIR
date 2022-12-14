from ..registry import DETECTORS
from .two_stage import TwoStageDetector


@DETECTORS.register_module
class FasterRCNN(TwoStageDetector):

    def __init__(self,
                 backbone,
                 rpn_head,
                 bbox_roi_extractor,
                 bbox_head,
                 train_cfg,
                 test_cfg,
                 neck=None,
                 shared_head=None,
                 relation_head=None,
                 attr_head=None,
                 relcaption_head=None,
                 saliency_detector=None,
                 downstream_caption_head=None,
                 pretrained=None):
        super(FasterRCNN, self).__init__(
            backbone=backbone,
            neck=neck,
            shared_head=shared_head,
            rpn_head=rpn_head,
            bbox_roi_extractor=bbox_roi_extractor,
            bbox_head=bbox_head,
            relation_head=relation_head,
            attr_head=attr_head,
            relcaption_head=relcaption_head,
            saliency_detector=saliency_detector,
            downstream_caption_head=downstream_caption_head,
            train_cfg=train_cfg,
            test_cfg=test_cfg,
            pretrained=pretrained)
