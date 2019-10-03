# Kubernetes CRD for running Chaos Toolkit experiments on-demand

This repository contains a Kubernetes controller to run Chaos Toolkit
experiments on-demand by submitting custom-resource objects.

## How to deploy?

This repository comes with a set of manifests to deploy the controller into
your Kubernetes cluster.

We suggest you use [Kustomize][kustomize] to generate the manifest to apply.
Ensure to download the latest release and drop into your PATH. Recent versions
pf kubectl also ships it with the `kubectl apply -k ...` command but this
always seems to lag, so better download the latest release of Kustomize
directly.

[kustomize]: https://github.com/kubernetes-sigs/kustomize

The repository provides four variants to deploy:

* generic: no RBAC needed in your cluster
* generic with RBAC
* generic with RBAC and Pod Security
* generic with RBAC, Pod Security and Net security

All of them offer a base to work from but it is safe to assume you will have
your own specific parameters for your cluster.

Anyway, assuming you want to try one as-is. Simply run the following command:

```
$ kustomize build overlays/generic-rbac | kubectl apply -f -
```

This would use the RBAC variant.

The following will happen:

* the `chaostoolkit-crd` namespace will be created
* a service account will be created
* a CRD definition will be declared
* a config map, with a Chaos Toolkit pod template (and other resources) will be
  added
* the controller will be started as a deployment of a single replica

In addition, with the RBAC variant:

* a set of roles will be created so the controller can monitor for new
  custom-resource objects in the `chaostoolkit-crd` namespace but also to
  allow the creation of resources that will run the chaostoolkit

The pod-security variant will define fairly strict security rules so the
chaostoolkit pod can run safely.

The net-security variant will finally add enough network permissions so the
chaostoolkit pod can talk with the outside world.

If everything goes to plan, you should have the controller running:

```
$ kubectl -n chaostoolkit-crd logs -l app=chaostoolkit-crd
```

## Run Chaos Toolkit experiment

To trigger the creation of a Chaos Toolkit experiment, you need to submit
a resource of kind `ChaosToolkitExperiment` in the `chaostoolkit.org/v1` group.

A good example is as follows:

```yaml
---
apiVersion: v1
kind: Namespace
metadata:
  name: chaostoolkit-run
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: chaostoolkit-env
  namespace: chaostoolkit-run
data:
  EXPERIMENT_URL: "https://raw.githubusercontent.com/Lawouach/dummy/master/experiments/token.json"
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
```

We decide to execute those chaostoolkit in a namespace called
`chaostoolkit-run` so we create it first.

Then, we create a configmap that contains environment variables that will
be populated into the chaostoolkit pod. They will be available to your
Chaos Toolkit experiment that way.

Finally, we declare our experiment resource and simply state its namespace.

## Various configurations

You may decide to change various aspects of the final pod (such as passing
settings as secrets, changing the roles allowed to the pod, even overide
the entire pod template).

To be documented.


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

