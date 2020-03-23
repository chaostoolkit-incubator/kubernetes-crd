import asyncio
from functools import wraps, partial
import logging
import random
import string
from typing import Any, Dict, List, NoReturn, Union

import kopf
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
    """
    v1 = client.CoreV1Api()
    v1rbac = client.RbacAuthorizationV1Api()

    cm = await get_config_map(v1, spec, namespace)

    keep_resources_on_delete = spec.get("keep_resources_on_delete", False)
    if keep_resources_on_delete:
        logger.info("Resources will be kept even when the CRO is deleted")

    ns, ns_tpl = await create_ns(v1, cm, spec)
    if ns_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(ns_tpl, owner=body)
    logger.info(f"chaostoolkit resources will be created in namespace '{ns}'")

    name_suffix = generate_name_suffix()
    logger.info(f"Suffix for resource names will be '-{name_suffix}'")

    sa_tpl = await create_sa(v1, cm, spec, ns, name_suffix)
    if sa_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(sa_tpl, owner=body)
        logger.info(f"Created service account")

    role_tpl = await create_role(
        v1rbac, cm, spec, ns, name_suffix)
    if role_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(role_tpl, owner=body)
        logger.info(f"Created role")

    role_binding_tpl = await create_role_binding(
        v1rbac, cm, spec, ns, name_suffix)
    if role_binding_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(role_binding_tpl, owner=body)
        logger.info(f"Created rolebinding")

    cm_tpl = await create_experiment_env_config_map(
        v1, ns, spec.get("pod", {}).get("env", {}).get(
            "configMapName", "chaostoolkit-env"))
    if cm_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(cm_tpl, owner=body)
        logger.info(f"Created experiment's env vars configmap")

    pod_tpl = await create_pod(v1, cm, spec, ns, name_suffix)
    if pod_tpl:
        if not keep_resources_on_delete:
            kopf.adopt(pod_tpl, owner=body)
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


def set_sa_name(pod_tpl: Dict[str, Any], name_suffix: str) -> str:
    """
    Set the service account name of the pod

    Suffix with a random string so that we don't get conflicts.
    """
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
    """
    spec = pod_tpl["spec"]
    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            args_as_str = ' '.join(cmd_args)
            new_cmd = "/usr/local/bin/chaos {args} && exit $?".format(
                args=args_as_str)
            container["args"][-1] = new_cmd


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
        return v1.create_namespaced_config_map(namespace, body)


@run_async
def get_config_map(v1: client.CoreV1Api(), spec: Dict[str, Any],
                   namespace: str):
    cm_pod_spec_name = spec.get("template", {}).get(
        "name", "chaostoolkit-resources-templates")
    cm = v1.read_namespaced_config_map(
        namespace=namespace, name=cm_pod_spec_name)
    return cm


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
                cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    role_name = cro_spec.get("role", {}).get("name")
    if not role_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-role.yaml'])
        role_name = tpl["metadata"]["name"]
        role_name = f"{role_name}-{name_suffix}"
        tpl["metadata"]["name"] = role_name
        set_ns(tpl, ns)
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
               cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')

    pod_spec = cro_spec.get("pod", {})

    # did the user supply their own pod spec?
    tpl = pod_spec.get("template")

    # if not, let's use the default one
    if not tpl:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-pod.yaml'])
        image_name = pod_spec.get("image", "chaostoolkit/chaostoolkit")
        env_cm_name = pod_spec.get("env", {}).get(
            "configMapName", "chaostoolkit-env")
        env_cm_enabled = pod_spec.get("env", {}).get("enabled", True)
        settings_secret_enabled = pod_spec.get("settings", {}).get(
            "enabled", True)
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

        if cmd_args:
            logger.info(
                f"Override default chaos command arguments: "
                f"$ chaos {' '.join(cmd_args)}")
            set_chaos_cmd_args(tpl, cmd_args)

    set_ns(tpl, ns)
    set_pod_name(tpl, name_suffix=name_suffix)
    set_sa_name(tpl, name_suffix=name_suffix)

    logger.debug(f"Creating pod with template:\n{tpl}")
    pod = api.create_namespaced_pod(body=tpl, namespace=ns)
    logger.info(f"Pod {pod.metadata.self_link} created in ns '{ns}'")

    return tpl
