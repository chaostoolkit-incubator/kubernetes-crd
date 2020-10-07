# Kubernetes CRD/operator for running Chaos Toolkit experiments on-demand

[![Build Status](https://travis-ci.org/chaostoolkit-incubator/kubernetes-crd.svg?branch=master)](https://travis-ci.org/chaostoolkit-incubator/kubernetes-crd)
[![Docker Pulls](https://img.shields.io/docker/pulls/chaostoolkit/k8scrd)](https://hub.docker.com/r/chaostoolkit/k8scrd)

This repository contains a Kubernetes operator to control Chaos Toolkit
experiments on-demand by submitting custom-resource objects.

## How to deploy?

This repository comes with a set of manifests to deploy the controller into
your Kubernetes cluster.

We suggest you use [Kustomize][kustomize] to generate the manifest to apply.
Ensure to download the latest release and drop into your PATH. Recent versions
of kubectl also ships it with the `kubectl apply -k ...` command but this
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
$ kustomize build manifests/overlays/generic-rbac | kubectl apply -f -
```

This would use the RBAC variant.

The following will happen:

* the `chaostoolkit-crd` and `chaostoolkit-run` namespaces will be created
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
  name: chaostoolkit-experiment
  namespace: chaostoolkit-run
data:
  experiment.json: |
    {
        "title": "...",
    }
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
```

We decide to execute those chaostoolkit in the default `chaostoolkit-run` 
namespace. 
We create a configmap that contains the experiment as a file entry.
Finally, we declare our experiment resource that the operator listens for.

This will create, as soon as possible, a pod running the Chaos Toolkit with
the given experiment in the `chaostoolkit-run` namespace.

Obviously, you can create the `chaostoolkit-experiment` as follows too:

```console
$ kubectl -n chaostoolkit-run create configmap chaostoolkit-experiment \
    --from-file=experiment.json=./experiment.json
```

In the example above, the name of the config map holding the experiment is
the default value `chaostoolkit-experiment`. Usually, you'll want a more
unique name since you'll probably run multiple experiments from the
`chaostoolkit-run` namespace.

In that case, do it as follows:

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: chaostoolkit-experiment-1234
  namespace: chaostoolkit-run
data:
  experiment.json: |
    {
        "title": "...",
    }
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  pod:
    experiment:
      configMapName: chaostoolkit-experiment-1234
```

## Various configurations

You may decide to change various aspects of the final pod (such as passing
settings as secrets, changing the roles allowed to the pod, even override
the entire pod template).

### Run the experiment from a URL

Let's say you store your experiments remotely and make them available over
HTTP. You can tell the Chaos Toolkit to load it from there rather than from
a local file.

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: chaostoolkit-env
  namespace: chaostoolkit-run
data:
  EXPERIMENT_URL: https://example.com/experiment.json
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  pod:
    experiment:
        asFile: false
```

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

You may provide your own [settings][settings] to Chaos Toolkit, by setting a
secret in Kubernetes.

[settings]: https://docs.chaostoolkit.org/reference/usage/cli/#configure-the-chaos-toolkit

For instance, assuming a settings file, named `settings.yaml`:

```
$ kubectl -n chaostoolkit-run \
    create secret generic chaostoolkit-settings \
    --from-file=settings.yaml=./settings.yaml
```

The settings file must be named as `settings.yaml` within the secret.

Note, if you haven't ever created an execution via this CRD, you may need to
create the `chaostoolkit-run` namespace in which the chaostoolkit pods will
be started: `$ kubectl create namespace chaostoolkit-run`.

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
          - "/usr/local/bin/chaos run ${EXPERIMENT_PATH-$EXPERIMENT_URL} && exit $?"
          ...
```


### Override the default chaos command arguments

The pod template executes the `chaos run` command by default. You may want to
extends or change the sub-command to execute when running the pod. You can
define the `chaos` arguments as follow:


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
    chaosArgs:
    - --verbose
    - run
    - --dry
    - $(EXPERIMENT_PATH)
```

### Label your Chaos Toolkit experiment

Experiment labels can be defined in the `ChaosToolkitExperiment`'s metadata.
All labels will be forwarded, if not already defined, in the pod running the
experiment.

You can define labels as follow:

```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
  labels:
    experiment-url: https://example.com/experiment.json
    environment: staging
```


### Allow network traffic for Chaos Toolkit experiments

When the operator is installed with the net-security variant, the
`chaostoolkit` pod has limited network access. The pod is, by default,
isolated for ingress connectivity and is limited to only DNS lookup &
HTTPS for external traffic.

To allow the pod for other access, you may create another network policy
within the `chaostoolkit-run` namespace for pods matching the 
`app: chaostoolkit` label:

```yaml
---
kind: NetworkPolicy
apiVersion: networking.k8s.io/v1
metadata:
  name: my-custom-network-policy
  namespace: chaostoolkit-run
spec:
  podSelector:
    matchLabels:
      app: chaostoolkit
```

Below is an example to allow the pod accessing any URL via HTTP to external:
 
```yaml
---
kind: NetworkPolicy
apiVersion: networking.k8s.io/v1
metadata:
  name: allow-chaostoolkit-to-unsecure-external
  namespace: chaostoolkit-run
spec:
  podSelector:
    matchLabels:
      app: chaostoolkit
  policyTypes:
  - Egress
  egress:
  - to:
    - ipBlock:
        cidr: 0.0.0.0/0
    ports:
      - port: 80
        protocol: TCP
```

### Run periodic and recurring experiments

We support `crontab` schedule for running Chaos Toolkit experiments
periodically on a given schedule.

To do so, you can define a `.spec.schedule` section, as follow:

```yaml
---
apiVersion: chaostoolkit.org/v1
kind: ChaosToolkitExperiment
metadata:
  name: my-chaos-exp
  namespace: chaostoolkit-crd
spec:
  namespace: chaostoolkit-run
  schedule:
    kind: cronJob
    value: "*/1 * * * *"
``` 

This example runs a Chaos Toolkit experiment every minute.

You can check your scheduled experiments listing the kubernetes' `cronjob`
resource:

```
$ kubectl -n chaostoolkit-run get cronjobs
```

### List running Chaos Toolkit experiments

To list the running Chaos Toolkit experiments, use the `chaosexperiment` custom
resource name:

```
$ kubectl -n chaostoolkit-crd get chaosexperiments
```

To get details about the experiment, you can describe it:

```
$ kubectl -n chaostoolkit-crd describe chaosexperiment my-chaos-exp
```

You can also use the shorter versions of resource name: `ctks` and `ctk`.

### Delete a Chaos Toolkit experiment

Finished Chaos Toolkit experiments are not deleted automatically, regardless
their final status. To do so, delete the `ChaosToolkitExperiment`
resource from its name, using the following command:

```
$ kubectl -n chaostoolkit-crd delete chaosexperiment my-chaos-exp
```

As a reminder, all resources created to run this experiment will also be
deleted by default, unless the `keep_resources_on_delete` flag was set.


## Uninstall the operator

To uninstall the operator and all related resources, simple run the following
command for the overlay that is deployed.

```
$ kustomize build manifests/overlays/generic[-rbac[-podsec[-netsec]]] | kubectl delete -f -
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

