# Kubernetes CRD/operator for running Chaos Toolkit experiments on-demand

This repository contains a Kubernetes operator to control Chaos Toolkit
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
`chaostoolkit-run`. It will be created on the fly.

Then, we create a configmap that contains environment variables that will
be populated into the chaostoolkit pod. They will be available to your
Chaos Toolkit experiment that way.

Finally, we declare our experiment resource and simply state its namespace.

## Various configurations

You may decide to change various aspects of the final pod (such as passing
settings as secrets, changing the roles allowed to the pod, even overide
the entire pod template).

### Create the namespace for generated Kubernetes resources

You may create the namespace in which the resources will be deployed:

```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: my-chaostoolkit-run
```

If the namespace already exists, a message will be logged but this will not
abort the operation.

### Keep generated resources even when the CRO is deleted

When you delete the `ChaosToolkitExperiment` resource, all the allocated
resources are deleted too (namespace, pod, ...). To prevent this, you may
set the `keep_resources_on_delete` property. In that case, you are responsible
to cleanup all resources.

```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
  keep_resources_on_delete: true
```

### Pass Chaos Toolkit environment values

You may have declared configuration (or even secrets) to be read from the
process environment. You should pass them as follows:

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: chaostoolkit-env
  namespace: chaostoolkit-run
data:
  EXPERIMENT_URL: "https://raw.githubusercontent.com/Lawouach/dummy/master/experiments/token.json"
```

All the data of the config map will be injected as-is to the chaostoolkit pod.

### Pass Chaos Toolkit settings as a Kubernetes secret

You may provide your own [settings](settings) to Chaos Toolkit, by setting a
secret in Kubernetes.

[settings]: https://docs.chaostoolkit.org/reference/usage/cli/#configure-the-chaos-toolkit

For instance, assuming a settings file, named `settings.yaml`:

```
$ kubectl -n chaostoolkit-run \
    create secrets chaostoolkit-settings \
    --from-file=settings.yaml
```

Note, if you haven't ever created an execution via this CRD, you may need to
create the `chaostoolkit-run` namespace in which the chaostoolkit pods will
be started.

Now, you can enable the settings as a secret like this:


```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
  pod:
    settings:
      enabled: true
```

The default name for that secret is `chaostoolkit-settings` but you can change
this as follows:


```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
  pod:
    settings:
      enabled: true
      secretName: my-super-secret
```

### Pass your own role to bind to the service account

If your cluster has enabled RBAC, then the operator automatically binds a basic
role to the service account associated with the chaostoolkit pod. That role
allows your experiment to create/get/list/delete other pods in the same
namespace.

You probably have more specific requirements, here is how to do it:

```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
  role:
    name: my-role
```

The property `name` should be set to the name of the role you have created
in that namespace. The service account associated with the pod will be bound
to that role.

### Pass a full pod template

Sometimes, the default of this operator aren't just flexible enough. You may
pass your own pod template as follows:

```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
  pod:
    template:
      apiVersion: v1
      kind: Pod
      metadata:
      name: chaostoolkit
        labels:
          app: chaostoolkit
      spec:
        restartPolicy: Never
        serviceAccountName: chaostoolkit
        containers:
        - name: chaostoolkit
          image: chaostoolkit/chaostoolkit
          command:
          - "/bin/sh" 
          args:
          - "-c"
          - "/usr/local/bin/chaos run ${EXPERIMENT_URL} && exit $?"
          ...
```

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

