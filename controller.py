import asyncio
from functools import wraps, partial
import logging
import random
import string
from typing import Any, Dict, List, NoReturn, Union, Optional

import kopf
from kopf.toolkits.hierarchies import label
from kubernetes import client, config  # noqa: W0611
from kubernetes.client.rest import ApiException
import yaml


Resource = Dict[str, Any]
ResourceChunk = Dict[str, Any]


@kopf.on.create('chaostoolkit.org', 'v1', 'chaosexperiments')  # noqa: C901
async def create_chaos_experiment(
        meta: ResourceChunk, body: Dict[str, Any], spec: ResourceChunk,
        namespace: str, logger: logging.Logger, **kwargs) -> NoReturn:
    """
    Create a new pod running a Chaos Toolkit instance until it terminates.

    If experiment is scheduled, create a new cronJob that will periodically
    create a Chaos Toolkit instance.
    """
    v1 = client.CoreV1Api()
    v1rbac = client.RbacAuthorizationV1Api()
    v1policy = client.PolicyV1beta1Api()
    v1cron = client.BatchV1beta1Api()

    cm = await get_config_map(v1, spec, namespace)
    psp = await get_default_psp(v1policy)

    keep_resources_on_delete = spec.get("keep_resources_on_delete", False)
    if keep_resources_on_delete:
        logger.info("Resources will be kept even when the CRO is deleted")

    ns, ns_tpl = await create_ns(v1, cm, spec)
    if ns_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(ns_tpl, owner=body)
            await update_namespace(v1, ns, ns_tpl)
    logger.info(f"chaostoolkit resources will be created in namespace '{ns}'")

    name_suffix = generate_name_suffix()
    logger.info(f"Suffix for resource names will be '-{name_suffix}'")

    sa_tpl = await create_sa(v1, cm, spec, ns, name_suffix)
    if sa_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(sa_tpl, owner=body)
            await update_sa(v1, ns, sa_tpl)
        logger.info(f"Created service account")

    role_tpl = await create_role(
        v1rbac, cm, spec, ns, name_suffix, psp=psp)
    if role_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(role_tpl, owner=body)
            await update_role(v1rbac, ns, role_tpl)
        logger.info(f"Created role")

    role_binding_tpl = await create_role_binding(
        v1rbac, cm, spec, ns, name_suffix)
    if role_binding_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(role_binding_tpl, owner=body)
            await update_role_binding(v1rbac, ns, role_binding_tpl)
        logger.info(f"Created rolebinding")

    cm_tpl = await create_experiment_env_config_map(
        v1, ns, spec.get("pod", {}).get("env", {}).get(
            "configMapName", "chaostoolkit-env"))
    if cm_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(cm_tpl, owner=body)
            await update_config_map(v1, ns, cm_tpl)
        logger.info(f"Created experiment's env vars configmap")

    schedule = spec.get("schedule", {})
    if schedule:
        if schedule.get('kind').lower() == 'cronjob':
            # when schedule defined, we cannot create the pod directly,
            # we must create a cronJob with the pod definition
            pod_tpl = await create_pod(
                v1, cm, spec, ns, name_suffix, meta, apply=False)
            if pod_tpl:
                cron_tpl = await create_cron_job(
                    v1cron, cm, spec, ns, name_suffix, meta, pod_tpl=pod_tpl)
                if cron_tpl:
                    if not keep_resources_on_delete:
                        kopf.adopt(cron_tpl, owner=body)
                        await update_cron_job(v1cron, ns, cron_tpl)
                    logger.info("Chaos Toolkit scheduled")

    else:
        # create pod for running experiment right away
        pod_tpl = await create_pod(v1, cm, spec, ns, name_suffix, meta)
        if pod_tpl:
            if not keep_resources_on_delete:
                kopf.adopt(pod_tpl, owner=body)
                await update_pod(v1, ns, pod_tpl)
            logger.info("Chaos Toolkit started")


###############################################################################
# Internals
###############################################################################
def set_ns(resource: Union[Dict[str, Any], List[Dict[str, Any]]], ns: str):
    """
    Set the namespace on the resource(s)
    """
    if isinstance(resource, dict):
        resource["metadata"]["namespace"] = ns
    elif isinstance(resource, list):
        for r in resource:
            r["metadata"]["namespace"] = ns


def generate_name_suffix(suffix_length: int = 5) -> str:
    return ''.join(
        random.choices(
            string.ascii_lowercase + string.digits, k=suffix_length))


def set_pod_name(pod_tpl: Dict[str, Any], name_suffix: str) -> str:
    """
    Set the name of the pod

    Suffix with a random string so that we don't get conflicts.
    """
    pod_name = pod_tpl["metadata"]["name"]
    pod_name = f"{pod_name}-{name_suffix}"
    pod_tpl["metadata"]["name"] = pod_name
    return pod_name


def set_sa_name(pod_tpl: Dict[str, Any],
                name: str = None,
                name_suffix: str = None) -> str:
    """
    Set the service account name of the pod

    If name is given, we use it as is
    If name is not given, we use the default pod SA name
    with an optional suffix

    Suffix with a random string so that we don't get conflicts.
    """
    sa_name = name
    if not sa_name:
        sa_name = pod_tpl["spec"]["serviceAccountName"]
        sa_name = f"{sa_name}-{name_suffix}"
    pod_tpl["spec"]["serviceAccountName"] = sa_name


def set_image_name(pod_tpl: Dict[str, Any], image_name: str):
    """
    Set the image of the container.
    """
    for container in pod_tpl["spec"]["containers"]:
        if container["name"] == "chaostoolkit":
            container["image"] = image_name
            break


def set_env_config_map_name(pod_tpl: Dict[str, Any], env_cm_name: str):
    """
    Set the name of the config map containing environment variables passed
    to the pod for the experiment's configuration or secrets.
    """
    for container in pod_tpl["spec"]["containers"]:
        if container["name"] == "chaostoolkit":
            if "envFrom" in container:
                container["envFrom"][0]["configMapRef"]["name"] = env_cm_name
                break


def remove_settings_secret(pod_tpl: Dict[str, Any]):
    """
    Remove the secret volume and volume mounts from the pod.

    This is the case when no settings are provided.
    """
    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            for vm in container["volumeMounts"]:
                if vm["name"] == "chaostoolkit-settings":
                    container["volumeMounts"].remove(vm)
                    if len(container["volumeMounts"]) == 0:
                        container.pop("volumeMounts", None)
                    break

    for volume in spec["volumes"]:
        if volume["name"] == "chaostoolkit-settings":
            spec["volumes"].remove(volume)
            break

    if len(spec["volumes"]) == 0:
        spec.pop("volumes", None)


def remove_experiment_volume(pod_tpl: Dict[str, Any]):
    """
    Remove the experiment volume and volume mounts from the pod.

    This is the case when the experiment is passed as a URL via
    `EXPERIMENT_URL`.
    """
    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            for vm in container["volumeMounts"]:
                if vm["name"] == "chaostoolkit-experiment":
                    container["volumeMounts"].remove(vm)
                    if len(container["volumeMounts"]) == 0:
                        container.pop("volumeMounts", None)
                    break

    for volume in spec["volumes"]:
        if volume["name"] == "chaostoolkit-experiment":
            spec["volumes"].remove(volume)
            break

    if len(spec["volumes"]) == 0:
        spec.pop("volumes", None)


def remove_env_config_map(pod_tpl: Dict[str, Any]):
    """
    Remove the en mapping to the configmap, used to pass variables to the
    Chaos Toolkit.

    Disable it when you do not pass any environment variable.
    """
    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            for ef in container["envFrom"]:
                cmrf = ef.get("configMapRef")
                if cmrf and cmrf["name"] == "chaostoolkit-env":
                    container["envFrom"].remove(ef)
                    if len(container["envFrom"]) == 0:
                        container.pop("envFrom", None)
                    break


def add_env_secret(pod_tpl: Dict[str, Any], secret_name: str):
    """
    Add the secret name to be used as envFrom entry in the pod spec.

    See: https://kubernetes.io/docs/tasks/inject-data-application/distribute-credentials-secure/#configure-all-key-value-pairs-in-a-secret-as-container-environment-variables
    """  # noqa: E501
    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            container.setdefault("envFrom", []).append(
                {
                    "secretRef": {
                        "name": secret_name
                    }
                }
            )
            break


def remove_env_path_config_map(pod_tpl: Dict[str, Any]):
    """
    Remove the `EXPERIMENT_PATH` environment path because the experiment
    was set to be a URL via `EXPERIMENT_URL`.
    """
    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            for e in container["env"]:
                if e["name"] == "EXPERIMENT_PATH":
                    container["env"].remove(e)
                    break


def set_settings_secret_name(pod_tpl: Dict[str, Any], secret_name: str):
    """
    Set the secret volume and volume mounts from the pod.
    """
    spec = pod_tpl["spec"]
    for volume in spec["volumes"]:
        if volume["name"] == "chaostoolkit-settings":
            volume["secret"]["secretName"] = secret_name
            break


def set_experiment_config_map_name(pod_tpl: Dict[str, Any], cm_name: str):
    """
    Set the experiment config map volume and volume mounts from the pod.
    """
    spec = pod_tpl["spec"]
    for volume in spec["volumes"]:
        if volume["name"] == "chaostoolkit-experiment":
            volume["configMap"]["name"] = cm_name
            break


def set_chaos_cmd_args(pod_tpl: Dict[str, Any], cmd_args: List[str]):
    """
    Set the command line arguments for the chaos command

    Handle two syntax of the POD template command:
    * Legacy:
        command:
        - "/bin/sh"
        args:
        - "-c"
        - "/usr/local/bin/chaos run ${EXPERIMENT_PATH-$EXPERIMENT_URL} && exit $?"
    -> we need to inject the arguments into the last args command line string
    * New style:
        command:
        - "/usr/local/bin/chaos"
        args:
        - run
        - $(EXPERIMENT_PATH)
    -> we can directly replace the list of args by user's list
    Beware the new style args must use the K8s env vars syntax: $()
    See: https://kubernetes.io/docs/tasks/inject-data-application/define-command-argument-container/#use-environment-variables-to-define-arguments
    """  # noqa: E501
    # filter out empty values from command line arguments: None, ''
    cmd_args = list(filter(None, cmd_args))

    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            if "chaos" in container["command"][0]:
                # new style syntax: pod command is chaos command
                container["args"] = cmd_args
            else:
                # legacy syntax: pod command is a new shell
                args_as_str = ' '.join(cmd_args)
                new_cmd = "/usr/local/bin/chaos {args} && exit $?".format(
                    args=args_as_str)
                container["args"][-1] = new_cmd


def set_rule_psp_name(rule_tpl: Dict[str, Any], name: str) -> NoReturn:
    """
    Set the name of the PSP to be used on a role rule
    """
    if name:
        if rule_tpl["resources"] == ["podsecuritypolicies"]:
            rule_tpl["resourceNames"] = [name]


def set_cron_job_name(cron_tpl: Dict[str, Any], name_suffix: str) -> str:
    """
    Set the name of the cron job

    Suffix with a random string so that we don't get conflicts.
    """
    cron_name = cron_tpl["metadata"]["name"]
    cron_name = f"{cron_name}-{name_suffix}"
    cron_tpl["metadata"]["name"] = cron_name
    return cron_name


def set_cron_job_schedule(cron_tpl: Dict[str, Any], schedule: str) -> NoReturn:
    """
    Set the cron job schedule, if specifed, otherwise leaves default schedule
    """
    if not schedule:
        return

    cron_spec = cron_tpl.setdefault("spec", {})
    cron_spec["schedule"] = schedule


def set_cron_job_template_spec(
        cron_tpl: Dict[str, Any], tpl_spec: Dict[str, Any]) -> NoReturn:
    """
    Set the spec for the cron job template
    """
    cron_spec = cron_tpl.setdefault("spec", {})
    _tpl = cron_spec.setdefault(
        "jobTemplate", {}).setdefault(
        "spec", {}).setdefault(
        "template", {})
    _tpl["spec"] = tpl_spec


def run_async(func):
    @wraps(func)
    async def run(*args, loop=None, executor=None, **kwargs):
        if loop is None:
            loop = asyncio.get_event_loop()
        pfunc = partial(func, *args, **kwargs)
        return await loop.run_in_executor(executor, pfunc)
    return run


@run_async
def create_experiment_env_config_map(v1: client.CoreV1Api(), namespace: str,
                                     name: str = "chaostoolkit-env"):
    """
    Create the default configmap to hold experiment environment variables,
    in case it wasn't already created by the user.

    If it already exists, we do not return it so that the operator does not
    take its ownership.
    """
    logger = logging.getLogger('kopf.objects')
    try:
        v1.read_namespaced_config_map(
            namespace=namespace, name="chaostoolkit-env")
    except ApiException:
        logger.info("Creating default `chaostoolkit-env` configmap")
        body = client.V1ConfigMap(metadata=client.V1ObjectMeta(name=name))
        cm = v1.create_namespaced_config_map(namespace, body)
        return cm.to_dict()


@run_async
def get_config_map(v1: client.CoreV1Api(), spec: Dict[str, Any],
                   namespace: str):
    cm_pod_spec_name = spec.get("template", {}).get(
        "name", "chaostoolkit-resources-templates")
    cm = v1.read_namespaced_config_map(
        namespace=namespace, name=cm_pod_spec_name)
    return cm


@run_async
def get_default_psp(v1: client.PolicyV1beta1Api,
                    name: str = 'chaostoolkit-run'
                    ) -> Optional[client.PolicyV1beta1PodSecurityPolicy]:
    """
    Get the default PodSecurityPolicy for the CTK pod,
    if the CRD is installed with podsec variant.
    """
    logger = logging.getLogger('kopf.objects')
    try:
        return v1.read_pod_security_policy(name=name)
    except ApiException:
        logger.info("Default PSP for chaostoolkit not found.")


@run_async
def create_ns(api: client.CoreV1Api, configmap: Resource,
              cro_spec: ResourceChunk) -> Union[str, Resource]:
    """
    If it already exists, we do not return it so that the operator does not
    take its ownership.
    """
    logger = logging.getLogger('kopf.objects')
    ns_name = cro_spec.get("namespace", "chaostoolkit-run")
    tpl = yaml.safe_load(configmap.data['chaostoolkit-ns.yaml'])
    tpl["metadata"]["name"] = ns_name
    logger.debug(f"Creating namespace with template:\n{tpl}")
    try:
        api.create_namespace(body=tpl)
        return ns_name, tpl
    except ApiException as e:
        if e.status == 409:
            logger.info(
                f"Namespace '{ns_name}' already exists. Let's continue...",
                exc_info=False)
            return ns_name, None
        else:
            raise kopf.PermanentError(
                f"Failed to create namespace: {str(e)}")


@run_async
def create_sa(api: client.CoreV1Api, configmap: Resource,
              cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    sa_name = cro_spec.get("serviceaccount", {}).get("name")
    if not sa_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-sa.yaml'])
        sa_name = tpl["metadata"]["name"]
        sa_name = f"{sa_name}-{name_suffix}"
        tpl["metadata"]["name"] = sa_name
        set_ns(tpl, ns)
        logger.debug(f"Creating service account with template:\n{tpl}")
        try:
            api.create_namespaced_service_account(body=tpl, namespace=ns)
            return tpl
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Service account '{sa_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to create service account: {str(e)}")


@run_async
def create_role(api: client.RbacAuthorizationV1Api, configmap: Resource,
                cro_spec: ResourceChunk, ns: str, name_suffix: str,
                psp: client.PolicyV1beta1PodSecurityPolicy = None):
    logger = logging.getLogger('kopf.objects')
    role_name = cro_spec.get("role", {}).get("name")
    if not role_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-role.yaml'])
        role_name = tpl["metadata"]["name"]
        role_name = f"{role_name}-{name_suffix}"
        tpl["metadata"]["name"] = role_name
        set_ns(tpl, ns)

        # when a PSP is defined, we add a rule to use that PSP
        if psp:
            logger.info(
                f"Adding pod security policy {psp.metadata.name} use to role")
            psp_rule = yaml.safe_load(
                configmap.data['chaostoolkit-role-psp-rule.yaml'])

            set_rule_psp_name(psp_rule, psp.metadata.name)
            tpl["rules"].append(psp_rule)

        logger.debug(f"Creating role with template:\n{tpl}")
        try:
            api.create_namespaced_role(body=tpl, namespace=ns)
            return tpl
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Role '{role_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to create role: {str(e)}")


@run_async
def create_role_binding(api: client.RbacAuthorizationV1Api,
                        configmap: Resource, cro_spec: ResourceChunk, ns: str,
                        name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    role_bind_name = cro_spec.get("role", {}).get("bind")
    if not role_bind_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-role-binding.yaml'])
        role_binding_name = tpl["metadata"]["name"]
        role_binding_name = f"{role_binding_name}-{name_suffix}"
        tpl["metadata"]["name"] = role_binding_name

        # change sa subject name
        sa_name = tpl["subjects"][0]["name"]
        sa_name = f"{sa_name}-{name_suffix}"
        tpl["subjects"][0]["name"] = sa_name

        # change sa subject namespace
        tpl["subjects"][0]["namespace"] = ns

        # change role name
        role_name = tpl["roleRef"]["name"]
        role_name = f"{role_name}-{name_suffix}"
        tpl["roleRef"]["name"] = role_name

        set_ns(tpl, ns)
        logger.debug(f"Creating role binding with template:\n{tpl}")
        try:
            api.create_namespaced_role_binding(body=tpl, namespace=ns)
            return tpl
        except ApiException as e:
            if e.status == 409:
                logger.info(
                    f"Role binding '{role_binding_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to bind to role: {str(e)}")


@run_async
def create_pod(api: client.CoreV1Api, configmap: Resource,
               cro_spec: ResourceChunk, ns: str, name_suffix: str,
               cro_meta: ResourceChunk, *, apply: bool = True):
    logger = logging.getLogger('kopf.objects')

    pod_spec = cro_spec.get("pod", {})
    sa_name = cro_spec.get("serviceaccount", {}).get("name")

    # did the user supply their own pod spec?
    tpl = pod_spec.get("template")

    # if not, let's use the default one
    if not tpl:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-pod.yaml'])
        image_name = pod_spec.get("image", "chaostoolkit/chaostoolkit")
        env_cm_name = pod_spec.get("env", {}).get(
            "configMapName", "chaostoolkit-env")
        env_cm_enabled = pod_spec.get("env", {}).get("enabled", True)
        # optional support for loading secret keys as env. variables
        env_secret_name = pod_spec.get("env", {}).get("secretName")
        settings_secret_enabled = pod_spec.get("settings", {}).get(
            "enabled", False)
        settings_secret_name = pod_spec.get("settings", {}).get(
            "secretName", "chaostoolkit-settings")
        experiment_as_file = pod_spec.get(
            "experiment", {}).get("asFile", True)
        experiment_config_map_name = pod_spec.get("experiment", {}).get(
            "configMapName", "chaostoolkit-experiment")
        cmd_args = pod_spec.get("chaosArgs", [])

        set_image_name(tpl, image_name)

        if not env_cm_enabled:
            logger.info("Removing default env configmap volume")
            remove_env_config_map(tpl)
        elif env_cm_name:
            logger.info(f"Env config map named '{env_cm_name}'")
            set_env_config_map_name(tpl, env_cm_name)

        if env_secret_name and env_cm_enabled:
            logger.info(f"Adding secret '{env_secret_name}' "
                        f"as environment variables")
            add_env_secret(tpl, env_secret_name)

        if not settings_secret_enabled:
            logger.info("Removing default settings secret volume")
            remove_settings_secret(tpl)
        elif settings_secret_name:
            logger.info(
                f"Settings secret volume named '{settings_secret_name}'")
            set_settings_secret_name(tpl, settings_secret_name)

        if experiment_as_file:
            logger.info(
                f"Experiment config map named '{experiment_config_map_name}'")
            set_experiment_config_map_name(tpl, experiment_config_map_name)
        else:
            logger.info("Removing default experiment config map volume")
            remove_experiment_volume(tpl)
            remove_env_path_config_map(tpl)
            set_chaos_cmd_args(tpl, ["run", "$(EXPERIMENT_URL)"])

        if cmd_args:
            # filter out empty values from command line arguments: None, ''
            cmd_args = list(filter(None, cmd_args))
            logger.info(
                f"Override default chaos command arguments: "
                f"$ chaos {' '.join([str(arg) for arg in cmd_args])}")
            set_chaos_cmd_args(tpl, cmd_args)

    set_ns(tpl, ns)
    set_pod_name(tpl, name_suffix=name_suffix)
    set_sa_name(tpl, name=sa_name, name_suffix=name_suffix)
    label(tpl, labels=cro_meta.get('labels', {}))

    if apply:
        logger.debug(f"Creating pod with template:\n{tpl}")
        pod = api.create_namespaced_pod(body=tpl, namespace=ns)
        logger.info(f"Pod {pod.metadata.self_link} created in ns '{ns}'")

    return tpl


@run_async
def create_cron_job(api: client.BatchV1beta1Api, configmap: Resource,
                    cro_spec: ResourceChunk, ns: str, name_suffix: str,
                    cro_meta: ResourceChunk, pod_tpl: str):
    logger = logging.getLogger('kopf.objects')

    schedule_spec = cro_spec.get("schedule", {})
    schedule = schedule_spec.get("value")

    tpl = yaml.safe_load(configmap.data['chaostoolkit-cronjob.yaml'])
    set_ns(tpl, ns)
    set_cron_job_name(tpl, name_suffix=name_suffix)
    set_cron_job_schedule(tpl, schedule)
    set_cron_job_template_spec(tpl, pod_tpl.get("spec", {}))

    experiment_labels = cro_meta.get('labels', {})
    label(tpl, labels=experiment_labels)
    label(tpl["spec"]["jobTemplate"], labels=experiment_labels)
    label(tpl["spec"]["jobTemplate"]["spec"]["template"],
          labels=experiment_labels)

    logger.debug(f"Creating cron job with template:\n{tpl}")
    cron = api.create_namespaced_cron_job(body=tpl, namespace=ns)
    logger.info(f"Cron Job '{cron.metadata.self_link}' scheduled with "
                f"pattern '{schedule}' in ns '{ns}'")

    return tpl


@run_async
def update_namespace(api: client.CoreV1Api, name: str, body: str):
    return api.patch_namespace(name, body)


def _update_namespaced_resource(
        api: Union[client.CoreV1Api, client.RbacAuthorizationV1Api],
        ns: str,
        resource: str,
        body: str):
    name = body.get("metadata", {}).get("name")
    if not name:
        return

    api_func_name = f"patch_namespaced_{resource}"
    api_func = getattr(api, api_func_name)
    return api_func(name, ns, body)


@run_async
def update_sa(api: client.CoreV1Api, ns: str, body: str):
    return _update_namespaced_resource(
        api, ns, "service_account", body
    )


@run_async
def update_role(api: client.RbacAuthorizationV1Api, ns: str, body: str):
    return _update_namespaced_resource(
        api, ns, "role", body
    )


@run_async
def update_role_binding(api: client.RbacAuthorizationV1Api,
                        ns: str, body: str):
    return _update_namespaced_resource(
        api, ns, "role_binding", body
    )


@run_async
def update_config_map(api: client.CoreV1Api, ns: str, body: str):
    return _update_namespaced_resource(
        api, ns, "config_map", body
    )


@run_async
def update_pod(api: client.CoreV1Api, ns: str, body: str):
    return _update_namespaced_resource(
        api, ns, "pod", body
    )


@run_async
def update_cron_job(api: client.BatchV1beta1Api, ns: str, body: str):
    return _update_namespaced_resource(
        api, ns, "cron_job", body
    )
