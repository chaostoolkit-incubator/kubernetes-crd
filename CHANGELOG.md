# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [Unreleased][]

[Unreleased]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.3...HEAD

### Changed

-   Upgrade CRD to `apiextensions.k8s.io/v1` [#57][57]
-   Upgrade `kopf` to version 0.27 [#57][57]

[57]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/57


## [0.3.3][] - 2020-10-02

[0.3.3]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.2...0.3.3

### Changed

-   Fixes service account not used when name is defined [#64][64]

[64]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/64

## [0.3.2][] - 2020-09-07

[0.3.2]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.1...0.3.2

### Changed

-   Fixes error with empty value in `chaosArgs` list [#63][63]

[63]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/63

## [0.3.1][] - 2020-09-07

[0.3.1]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.0...0.3.1

### Changed

-   Fixes default pod args from environment variables [#47][47]
-   Fixes error when creating experiment default config map [#48][48]
-   Fixes error with empty value in `chaosArgs` list [#63][63]

[47]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/47
[48]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/48
[63]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/63

## [0.3.0][] - 2020-05-05

[0.3.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.2.0...0.3.0

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

[0.2.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.1.0...0.2.0

## [0.1.0][] - 2019-07-24

[0.1.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/tree/0.1.0

### Added

-   Initial release