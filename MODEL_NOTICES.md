# Recognition models and third-party notices

The app runs CPU ONNX inference locally. It downloads model weights only from pinned
OpenCV Zoo commit `48b10fa505aeb51fbd127fc60a5c660040e823b7`, checks their size and SHA-256,
then reuses them offline. `app/model_catalog.json` contains the exact sources and hashes.
The weights are not bundled and no photo or appearance vector is uploaded by recognition.

| Stage | Model | Download |
| --- | --- | --- |
| Text regions | PP-OCRv3 English detector | 2,423,490 bytes |
| Bib text | CRNN CH (digits and case-sensitive Latin) | 64,906,971 bytes |
| Rider bodies | NanoDet COCO person detector | 3,800,954 bytes |
| Whole-body appearance | Youtu ReID, 768 dimensions | 106,878,407 bytes |

Sources, model descriptions and original inference adapters:

- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/text_detection_ppocr>
- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/text_recognition_crnn>
- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/object_detection_nanodet>
- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/person_reid_youtureid>

The models and adapters carry Apache-2.0 licenses, copied verbatim under `licenses/`.
PP-OCR's notice credits the PaddlePaddle Authors. The text and ReID adapter notices
credit Shenzhen Institute of Artificial Intelligence and Robotics for Society (2021).
Third-party copyrights remain their owners'. The app's Pillow/NumPy preprocessing and
postprocessing adapt those model interfaces for ONNX Runtime without an OpenCV dependency.

There is no face detector, face embedding model, selfie search or face database.
ReID describes the full person crop (kit, helmet and build, with surrounding bike pixels
where they fall in that crop). Similar clothing and unusual riding poses can confuse it.
These general-purpose models are not calibrated on the pilot races yet; scores are model
similarities, not probabilities that a photo depicts a particular person.
