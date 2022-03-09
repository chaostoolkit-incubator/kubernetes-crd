# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased][]

[Unreleased]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.6.0...HEAD

### Changed

- Extended basic role given to experiment service account so that it can do a
  bit more
- Ensured default RBAC was deployed in target namespaces so that an experiment
  can perform actions againt these namespaces

## [0.6.0][] - 2021-06-08

[0.6.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.5.0...0.6.0

### Added

- Support for setting the experiment as a YAML file [#71][71]
- Delete handler so that resources are deleted when experiment object is deleted
- Upgraded various API to match Kubernetes 1.22
- Upgraded Kubernetes and Google auth libraries

[71]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/71

## [0.5.0][] - 2021-06-08

[0.5.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.4...0.5.0

### Changed

- Updated RBAC to match kopf [definition][rbac]
- Updated dependencies to latest kopf and kubernetes client

[rbac]: https://kopf.readthedocs.io/en/stable/deployment/#rbac

## [0.4.0][] - 2021-04-25

[0.4.0]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.4...0.4.0

### Changed

- Moved container image to use Python 3.9
- Upgrade `kopf` to version 1.30
- Upgrade `kubernetes` client to version 12.0

### Fixed

- Resources created by the controller were immediately deleted by kopf. They
  are not anymore.

## [0.3.4][] - 2020-10-16

[0.3.4]: https://github.com/chaostoolkit-incubator/kubernetes-crd/compare/0.3.3...0.3.4

### Changed

-   Upgrade CRD to `apiextensions.k8s.io/v1` [#57][57]
-   Upgrade `kopf` to version 0.27 [#57][57]

### Fixed

-   Keep default docker image from POD template, when not overridden in Experiment CRO [#67][67]
-   Fix the finalizers issue when apply the ownerreference in serviceaccount [#60][60]

[57]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/57
[67]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/67
[60]: https://github.com/chaostoolkit-incubator/kubernetes-crd/issues/60


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