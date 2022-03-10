# Kubernetes CRD/operator for running Chaos Toolkit experiments on-demand

[![Build](https://github.com/chaostoolkit-incubator/kubernetes-crd/actions/workflows/ci.yaml/badge.svg)](https://github.com/chaostoolkit-incubator/kubernetes-crd/actions/workflows/ci.yaml)
[![Docker Pulls](https://img.shields.io/docker/pulls/chaostoolkit/k8scrd)](https://hub.docker.com/r/chaostoolkit/k8scrd)

This repository contains a Kubernetes operator to control Chaos Toolkit
experiments on-demand by submitting custom-resource objects.

Read its [documentation][doc].

[doc]: https://chaostoolkit.org/deployment/k8s/operator/

## Contribute

If you wish to contribute more functions to this package, you are more than
welcome to do so. Please fork this project, make your changes following the
usual [PEP 8][pep8] code style, add appropriate tests and submit a PR for
review.

[pep8]: https://pycodestyle.readthedocs.io/en/latest/

The Chaos Toolkit projects require all contributors must sign a
[Developer Certificate of Origin][dco] on each commit they would like to merge
into the master branch of the repository. Please, make sure you can abide by
the rules of the DCO before submitting a PR.

[dco]: https://github.com/probot/dco#how-it-works

