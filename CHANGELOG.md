# Changelog

## [0.8.1](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.8.0...sport-photo-indexer-v0.8.1) (2026-10-28)


### Bug Fixes

* build no unused TLS context for each model source ([b966df7](https://github.com/dchernykh1984/SportPhotoIndexer/commit/b966df796a8c007efd561833bbbe633a265111df))
* close a model source's error response before trying the next source ([c8c8d62](https://github.com/dchernykh1984/SportPhotoIndexer/commit/c8c8d621c88f45fc323b8740111db0ff8f7df636))
* end a model download as a Stop when Stop shuts its socket between two ssl checks ([b9651cf](https://github.com/dchernykh1984/SportPhotoIndexer/commit/b9651cff8c111a0ed2ed1f330bdcba7fe788dff1))
* end a model download at once when Stop is pressed while its source sends nothing ([057a39b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/057a39b92b012333983a030a53924b9eaf10bbbc))
* give a model's host 15 seconds to answer and a minute between data ([5049856](https://github.com/dchernykh1984/SportPhotoIndexer/commit/504985681c0c0457e147182d722fd6fa1b00c15a))
* move on to a model's next source when a host fails before sending its headers ([2d0f142](https://github.com/dchernykh1984/SportPhotoIndexer/commit/2d0f1422abc20dab459d2e5c8a55239a42cb4c80))
* move on to a model's next source when the network fails in the middle of a file ([f5c397e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/f5c397ee11955d7c0388314dd842142d9b31660c))
* open no other source of a model once Stop is pressed while one fails ([ac22f1f](https://github.com/dchernykh1984/SportPhotoIndexer/commit/ac22f1f97d294b1f8c0fbc2d10f6e98a067b1b33))


### Documentation

* make a review cycle fix every valid finding and green the pipeline before it asks anything ([e5c6433](https://github.com/dchernykh1984/SportPhotoIndexer/commit/e5c643395f3db4d82af5589055676a82a7c427be))
* say when the model check fails and what it asks for ([a5d716c](https://github.com/dchernykh1984/SportPhotoIndexer/commit/a5d716c2efca09395f5a563dca49a6e2c527237d))

## [0.8.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.7.1...sport-photo-indexer-v0.8.0) (2026-10-28)


### Features

* download a model from its byte-identical copy when its first source fails ([240550b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/240550b68a8f9cafaf89cfd4ffa08b8c15da9571))
* look for a model in this repository's models-v1 release when its sources fail ([4c03d25](https://github.com/dchernykh1984/SportPhotoIndexer/commit/4c03d2580f42810ce87be0c772f433d480c90c43))


### Bug Fixes

* stop trying a model's other sources when the disk, not the source, fails ([8858338](https://github.com/dchernykh1984/SportPhotoIndexer/commit/8858338d023f8790127d0431bfedd446f4e22bdb))
* wait a minute for a stalled model download before trying the next source ([1fcef2b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/1fcef2b9f0fec6d6a0ab073b801414f4623d4bab))


### Documentation

* say that the bib reader's only fallback is the repository's release ([ce4d0ae](https://github.com/dchernykh1984/SportPhotoIndexer/commit/ce4d0ae5dd91a991e1dfdcd15300aacbe1eae961))
* say where a model comes from when its first source fails and how the mirror is filled ([05f74c6](https://github.com/dchernykh1984/SportPhotoIndexer/commit/05f74c6b0e73aaffd4c24c64be32e1ee7f1097ea))

## [0.7.1](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.7.0...sport-photo-indexer-v0.7.1) (2026-10-28)


### Documentation

* give the app's current share of found bibs in the album indexing skill ([4667b91](https://github.com/dchernykh1984/SportPhotoIndexer/commit/4667b91a6da4626638d5eb0c6e600ae7d5bf484b))

## [0.7.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.6.0...sport-photo-indexer-v0.7.0) (2026-10-28)


### Features

* read plates too small for the person windows in finer ones with the Florence-2 model sizes ([cc0be01](https://github.com/dchernykh1984/SportPhotoIndexer/commit/cc0be01a25c0635d138697152ce1e99b4c2553bd))


### Bug Fixes

* drop a lone digit the finer windows read inside a longer bib they also read ([7ca15d1](https://github.com/dchernykh1984/SportPhotoIndexer/commit/7ca15d14bcd8bfe07f684df3fca35a78efd302d7))
* judge a finer read's size by the tallest rider whose zone holds it ([7dd9239](https://github.com/dchernykh1984/SportPhotoIndexer/commit/7dd9239e79d2d3f90081473290dbeba46951cd28))
* let the finer windows add one vote per spot and never displace a bib read before ([8e67b8f](https://github.com/dchernykh1984/SportPhotoIndexer/commit/8e67b8f9507bef10e1500753eea09469a2c5bcfd))
* let the finer windows read a bib where only a discarded guess was read before ([0ad65c3](https://github.com/dchernykh1984/SportPhotoIndexer/commit/0ad65c3cad6fb424beea0533d1215002e55c2bb5))
* skip digits too small for a bib on the rider in the finer windows ([3aea75e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/3aea75e5e850f5156e287893252a8209336a87e2))


### Documentation

* give the finer windows' gains, wrong values and time on the labelled races ([fb8a0ab](https://github.com/dchernykh1984/SportPhotoIndexer/commit/fb8a0ab7c8553bc80fe960cfbd038cd5b7d497ba))
* say which way of indexing an album fits which need, the album skills included ([e791d2e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/e791d2e2febff5c220d7286520ff404bcaa66957))

## [0.6.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.5.0...sport-photo-indexer-v0.6.0) (2026-10-28)


### Features

* default to the Large models and matching riders by appearance and faces ([3ee084d](https://github.com/dchernykh1984/SportPhotoIndexer/commit/3ee084dce37675f428d2bb2e02b27ab7615df619))


### Bug Fixes

* cancel a window's pending reopen or close when the window is deleted ([41f1328](https://github.com/dchernykh1984/SportPhotoIndexer/commit/41f1328a7811d85d617004de7096566bd3fb360a))
* close the window only after a stopped scan's warning has been seen ([0e3f6ad](https://github.com/dchernykh1984/SportPhotoIndexer/commit/0e3f6adb19be24b2000df70a35c001192de31541))
* decode a large photo straight to screen size so it shows quickly and above 64 MP at all ([f7e8036](https://github.com/dchernykh1984/SportPhotoIndexer/commit/f7e803639eb7dadc80b2ace3672e198267d9187a))
* destroy the window before Python exits so no signal connection can crash the close ([b0eb5db](https://github.com/dchernykh1984/SportPhotoIndexer/commit/b0eb5dbb6a066faf0dca4aff8568b6074f667893))
* end any running worker thread before the window is destroyed on exit ([c517147](https://github.com/dchernykh1984/SportPhotoIndexer/commit/c517147504409e7c6a2cc9e964fec8469d1a5cdf))
* give a larger window to a larger photo instead of to the photo list ([fc2df24](https://github.com/dchernykh1984/SportPhotoIndexer/commit/fc2df24cc12fa1b587625e4032f05bee8337d948))
* keep a photo sharp when the window moves to a sharper screen ([5d6a8ae](https://github.com/dchernykh1984/SportPhotoIndexer/commit/5d6a8aec4168f43450180217c3f5d54c376c6efc))
* keep saying the work is stopping until it has stopped instead of showing a stale count ([dfa844a](https://github.com/dchernykh1984/SportPhotoIndexer/commit/dfa844af31bbcc868c87e9570738c3618d77e925))
* keep the folder check's progress readable by switching off only the controls ([5342ec7](https://github.com/dchernykh1984/SportPhotoIndexer/commit/5342ec7a0b3618467539bd0bec18233b42484e71))
* keep the window responsive while a large album is opened or rescanned ([cd2e1cd](https://github.com/dchernykh1984/SportPhotoIndexer/commit/cd2e1cda5dcfbbf4dd14ee350d1c2d7e0b7f2eda))
* keep window resizing smooth with large photos by holding at most a screenful of each ([1e491b9](https://github.com/dchernykh1984/SportPhotoIndexer/commit/1e491b9c3d3b16b7877fe1e1ca4869e36f4e2876))
* say when the folder check is stopping, stopped or failed instead of leaving its count behind ([e45e451](https://github.com/dchernykh1984/SportPhotoIndexer/commit/e45e4519b0809d811e3c63f2d7ad3daa9ecd3b29))
* show a photo the camera stored sideways upright ([1425bb9](https://github.com/dchernykh1984/SportPhotoIndexer/commit/1425bb9d209dd10e5b5962bb8ab4f9a8977f81cb))
* stop an album scan instead of freezing the window when its wait ends early ([432571c](https://github.com/dchernykh1984/SportPhotoIndexer/commit/432571cd5213fffc6f3c3593639de91ade95c7ea))
* stop the app crashing when it closes ([a99a4fb](https://github.com/dchernykh1984/SportPhotoIndexer/commit/a99a4fb4616e71f87aa31e892ee73bdae5bf7da2))


### Documentation

* give the downloads of the default mode and of the small models in it ([e8c7fec](https://github.com/dchernykh1984/SportPhotoIndexer/commit/e8c7feca11d969573f8fd062749653562b8a1a41))

## [0.5.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.4.0...sport-photo-indexer-v0.5.0) (2026-10-28)


### Features

* reject read bibs that are not in an optional start protocol chosen per album ([d3c018e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/d3c018ed9bceda63370e0c6ecda464eab64e2551))


### Bug Fixes

* drop older appearance suggestions outside the start protocol on a numbers-only run ([b7ed4ae](https://github.com/dchernykh1984/SportPhotoIndexer/commit/b7ed4aef03e87081743e92a68a1d94dbd381a53b))
* keep a bib the start protocol hid out of the rejections of the person who checks the photo ([4f1aecc](https://github.com/dchernykh1984/SportPhotoIndexer/commit/4f1aecc2556e1dd735a52319bbdb2acb103a0ca1))
* keep suggestions of a bib a person typed on a numbers-only run with a start protocol ([24fc66b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/24fc66bd752647a016fd6629f31c613e98032531))
* let the search mode and model size be chosen before an album is open ([df9fd5b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/df9fd5b667dca556b5c85212f2cdc74ae8e9fc9b))
* match the start protocol's bibs whatever their leading zeroes and case ([c24ec0e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/c24ec0e8a0b1a267276cf210fe6c316eee3de3ee))
* read quoted spreadsheet protocols and refuse a protocol whose first column holds no bibs ([ded4049](https://github.com/dchernykh1984/SportPhotoIndexer/commit/ded40497364e5af65248077b7d5efb5098709939))
* save a bib matched to the start protocol as the protocol spells it so the site finds the rider ([3246da3](https://github.com/dchernykh1984/SportPhotoIndexer/commit/3246da37ac1eccee0e5c544a51efdf11e438f9ae))
* show which bibs a start protocol gave and say when it is cleared ([82df75d](https://github.com/dchernykh1984/SportPhotoIndexer/commit/82df75d4a51c48650b07675f35e788d778be68c0))
* stop recognition when the album's start protocol file is missing instead of running without it ([2bcdb05](https://github.com/dchernykh1984/SportPhotoIndexer/commit/2bcdb0527d6c261906921a1f1a58c153ebf7aae8))


### Documentation

* record what a start protocol removes and what it cannot on the labelled races ([9e7fbc3](https://github.com/dchernykh1984/SportPhotoIndexer/commit/9e7fbc3ca7d014a32783fad6be30b52048452d2e))
* say how the start protocol shows its bibs and spells the bibs it matches ([d36c67d](https://github.com/dchernykh1984/SportPhotoIndexer/commit/d36c67d0df451e304cff895300e98031cfe1e099))

## [0.4.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.3.0...sport-photo-indexer-v0.4.0) (2026-10-28)


### Features

* add an appearance mode that matches riders by face as well as by body ([64d1543](https://github.com/dchernykh1984/SportPhotoIndexer/commit/64d1543977b057976c7726d477951cc91fdc268d))
* choose the model size in the window and remember it ([9a6fbfe](https://github.com/dchernykh1984/SportPhotoIndexer/commit/9a6fbfe7a8b09cbaafa2fbaca6e173108231d8ea))
* offer full-precision Florence-2 base as the largest size instead of 8-bit Florence-2 large ([cbe6edf](https://github.com/dchernykh1984/SportPhotoIndexer/commit/cbe6edf75e94a26ca9e57e82b26e000bce2bc3c7))
* offer larger model sizes that read bibs with Florence-2 beside the small reader ([dd581d6](https://github.com/dchernykh1984/SportPhotoIndexer/commit/dd581d6bf200cdb1530c68d29ff5aabec9ab4e59))
* read bibs in enlarged windows around each person with the detector's own input scaling ([b18a22d](https://github.com/dchernykh1984/SportPhotoIndexer/commit/b18a22d130165f9c045304b4dff453ee5467611b))
* read texts and their regions with Florence-2 on ONNX Runtime ([de45577](https://github.com/dchernykh1984/SportPhotoIndexer/commit/de45577f6f3172ee0e409568183c2b13b4b9b38d))


### Bug Fixes

* accept bibs with letters on the same terms as digits so any bib format works ([9aad45e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/9aad45ec230574d82fec5ed9ecfa2e5dc0af0ecb))
* accept digits from 0.95, a lone digit from 0.99, and keep lettered reads as suggestions ([37bbdc0](https://github.com/dchernykh1984/SportPhotoIndexer/commit/37bbdc0c56916067bed251435fe279088e4b1ece))


### Documentation

* record recognition precision and recall on two hand-labelled races ([0411613](https://github.com/dchernykh1984/SportPhotoIndexer/commit/0411613425446423b75109545c9070d4c2a4f7f5))
* record what each model size finds and costs, and what faces add, on the labelled races ([76bb145](https://github.com/dchernykh1984/SportPhotoIndexer/commit/76bb145d4b36d35d8bf1ab7363c3e6468243d26f))

## [0.3.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.2.0...sport-photo-indexer-v0.3.0) (2026-10-27)


### Features

* index HEIC and other photo formats without changing originals ([b7a6983](https://github.com/dchernykh1984/SportPhotoIndexer/commit/b7a69832ad9497625e834bdcbcfcac3d6c4ffd02))
* recognize photos in parallel within the available CPU budget ([28473b0](https://github.com/dchernykh1984/SportPhotoIndexer/commit/28473b0ae682eda0c2e9196fd398f1db7814bfd3))


### Bug Fixes

* honor Stop while checking cached recognition results ([3a88212](https://github.com/dchernykh1984/SportPhotoIndexer/commit/3a88212cdd29958c1a077abe246595d9e5927786))
* keep processing when a cached photo becomes unavailable ([8b29f3e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/8b29f3ebc6f03ee8deebc2328fbaf2e3464c20df))
* rebuild camera previews when their cached bytes were modified ([c823b6b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/c823b6ba53563b2f7b4e02cc4f08dc430ebc9501))
* report unavailable AVIF decoding on Windows ARM64 ([5e625a3](https://github.com/dchernykh1984/SportPhotoIndexer/commit/5e625a372c2791b14f690242494f476078198eeb))
* reuse unchanged camera previews when rescanning an album ([014f47d](https://github.com/dchernykh1984/SportPhotoIndexer/commit/014f47dee0e3b266854b666d19f4bc4ef6628124))
* show readable originals when optional previews are unavailable ([cf28236](https://github.com/dchernykh1984/SportPhotoIndexer/commit/cf28236e2f73c745411fe73468c614d79ebc110b))

## [0.2.0](https://github.com/dchernykh1984/SportPhotoIndexer/compare/sport-photo-indexer-v0.1.0...sport-photo-indexer-v0.2.0) (2026-10-27)


### Features

* recognize bibs then find riders by appearance on the local CPU ([050ace4](https://github.com/dchernykh1984/SportPhotoIndexer/commit/050ace4d214a2c89d5735a99cc0b2e5c2cb57346))


### Bug Fixes

* keep the window usable when an album cannot be scanned ([78f2bcb](https://github.com/dchernykh1984/SportPhotoIndexer/commit/78f2bcbfc977522ca6f5a012d46d06c870a74415))
* measure the index size using its published JSON encoding ([93a8410](https://github.com/dchernykh1984/SportPhotoIndexer/commit/93a841042a5b338ca530ebcf5e4b98222342511c))
* preserve photo proportions in rider detection ([0d559c5](https://github.com/dchernykh1984/SportPhotoIndexer/commit/0d559c5602eff6ed8c5249603160f92d3c356132))
* read small bibs in overlapping high-resolution photo tiles ([cfcdf69](https://github.com/dchernykh1984/SportPhotoIndexer/commit/cfcdf6918845a29cd8a092f5ba1f1c95a850228c))
* report successful imports only after their index is saved ([5ceb23b](https://github.com/dchernykh1984/SportPhotoIndexer/commit/5ceb23b62fbc9e302e196566851786e3318bc413))
* respect known bibs when matching a rider appearance ([5e6bbcf](https://github.com/dchernykh1984/SportPhotoIndexer/commit/5e6bbcfb7fa769d3438141a1f88157416583afcc))
* restore reviewed bibs when an unchanged photo returns to the album ([e5236e8](https://github.com/dchernykh1984/SportPhotoIndexer/commit/e5236e8184ddb85680282aaed6868a7600f27375))
* validate the complete photo index contract before writing ([d433d8e](https://github.com/dchernykh1984/SportPhotoIndexer/commit/d433d8e9cd47a08cc5f6a7da0a04a6f1a6977463))


### Performance Improvements

* calibrate accepted OCR reads from the race-photo audit ([7c66022](https://github.com/dchernykh1984/SportPhotoIndexer/commit/7c66022204a4afd5ea9fcb7f1839cb847559d3f3))
* use the smaller PaddleOCR reader validated on race photos ([bb25304](https://github.com/dchernykh1984/SportPhotoIndexer/commit/bb25304482eb3e5d6774496159f5e2c79e3d51a2))

## 0.1.0 (2026-10-26)


### Features

* scan an album folder into a photo-index.v1.json the site accepts, keeping ids and typed bibs ([8834775](https://github.com/dchernykh1984/SportPhotoIndexer/commit/88347755a0ca2101f2542c3c3f21f822d62e9eab))
* type each photo's bibs in a window that saves after every photo and moves to the next ([0790663](https://github.com/dchernykh1984/SportPhotoIndexer/commit/079066359967ff857135d319ea69a9d8693f5708))


### Bug Fixes

* keep a returning photo's id and remake previews that no longer match their photo ([e8a85fc](https://github.com/dchernykh1984/SportPhotoIndexer/commit/e8a85fc48517662425ad04d57c1644f651890d97))
* name the version in a frozen build without package metadata ([4ee2b1f](https://github.com/dchernykh1984/SportPhotoIndexer/commit/4ee2b1f1c7139f86b1e955f4280a99535744b1ca))
* refuse to overwrite a newer index or to write one over the site's size limit ([19b4102](https://github.com/dchernykh1984/SportPhotoIndexer/commit/19b41022dd2c12e2bfdc6c364b5d30f09fdc5aa7))


### Documentation

* explain how to index an album, share it and connect it to the event ([1a80ed3](https://github.com/dchernykh1984/SportPhotoIndexer/commit/1a80ed384c656985f6c565869550c98ee34b1d9b))
* state the site's and Dropbox's limits for an album ([4251293](https://github.com/dchernykh1984/SportPhotoIndexer/commit/4251293cb6f6b375b864bc51284802e012fa416e))

## Changelog
