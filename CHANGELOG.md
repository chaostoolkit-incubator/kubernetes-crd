# Changelog

## [Unreleased][]

[Unreleased]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.0...HEAD

### Changed

-   Fixes error when creating experiment default config map [#48][48]

[48]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/48

## [0.3.0][] - 2020-05-05

[0.3.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/tree/0.3.0

### Added 

-   Cron job support for scheduling experiments [#43][43]
-   Load Kubernetes secret as environment variables into pod [#38][38]
-   Add support for overriding `chaos` command arguments [#21][21]

### Changed

-   Handles pod interruption when deleting a running experiment [#44][44]
-   Fixes deletion of Chaos Experiment related resources [#6][6]

[44]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/44
[43]: https://github.com/chaostoolkit-incubator/kubernetes-crd/pull/43
[38]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/38
[21]: https://github.com/chaostoolkit-incubator/kubernetes-crd/pull/21
[6]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/6

## [0.2.0][] - 2020-02-09

[0.2.0]: https://github.com/chaostoolkit/chaostoolkit/compare/0.1.0...0.2.0

## [0.1.0][] - 2019-07-24

[0.1.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/tree/0.1.0

### Added

-   Initial release