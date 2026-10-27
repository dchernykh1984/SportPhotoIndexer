# Changelog

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
