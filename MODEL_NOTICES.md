# Recognition models and third-party notices

The app runs CPU ONNX inference locally. It downloads model weights only from pinned
OpenCV Zoo commit `48b10fa505aeb51fbd127fc60a5c660040e823b7` and the RapidOCR v3.9.2
model release, checks their size and SHA-256,
then reuses them offline. `app/model_catalog.json` contains the exact sources and hashes.
The weights are not bundled and no photo or appearance vector is uploaded by recognition.

| Stage | Model | Download |
| --- | --- | --- |
| Text regions | PP-OCRv3 English detector | 2,423,490 bytes |
| Bib text | PP-OCRv5 English mobile (embedded character dictionary) | 7,872,351 bytes |
| People (where to read bibs; rider bodies) | NanoDet COCO person detector | 3,800,954 bytes |
| Whole-body appearance | Youtu ReID, 768 dimensions | 106,878,407 bytes |

Sources, model descriptions and original inference adapters:

- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/text_detection_ppocr>
- <https://github.com/RapidAI/RapidOCR/blob/80b427d69bfc5b91a12913394875910296c6f315/python/rapidocr/default_models.yaml>
- <https://github.com/RapidAI/RapidOCR/blob/80b427d69bfc5b91a12913394875910296c6f315/python/rapidocr/ch_ppocr_rec/main.py>
- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/object_detection_nanodet>
- <https://github.com/opencv/opencv_zoo/tree/48b10fa505aeb51fbd127fc60a5c660040e823b7/models/person_reid_youtureid>

The models and adapters carry Apache-2.0 licenses retained under `licenses/`.
The reader is PaddleOCR converted to ONNX by RapidOCR; its embedded dictionary supplies
the exact case-sensitive token order. A legacy CRNN adapter notice is retained as well.
PP-OCR's notice credits the PaddlePaddle Authors. The text and ReID adapter notices
credit Shenzhen Institute of Artificial Intelligence and Robotics for Society (2021).
Third-party copyrights remain their owners'. The app's Pillow/NumPy preprocessing and
postprocessing adapt those model interfaces for ONNX Runtime without an OpenCV dependency.

There is no face detector, face embedding model, selfie search or face database.
ReID describes the full person crop (kit, helmet and build, with surrounding bike pixels
where they fall in that crop). Similar clothing and unusual riding poses can confuse it.
The models have been exercised on the pilot race photos, but full ground-truth calibration
is still pending. Scores are model
similarities, not probabilities that a photo depicts a particular person.
