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


@kopf.on.create('chaostoolkit.org', 'v1', 'chaosexperiments')
async def create_chaos_experiment(
        meta: ResourceChunk, body: Dict[str, Any], spec: ResourceChunk,
        namespace: str, logger: logging.Logger, **kwargs) -> NoReturn:
    """
    Create a new pod running a Chaos Toolkit instance until it terminates.
    """
    v1 = client.CoreV1Api()
    v1rbac = client.RbacAuthorizationV1Api()

    ns = spec.get("namespace", namespace)
    logger.info(f"chaostoolkit resources will be created in namespace '{ns}'")

    name_suffix = generate_name_suffix()

    cm_pod_spec_name = spec.get("template", {}).get(
        "name", "chaostoolkit-resources-templates")
    cm = v1.read_namespaced_config_map(
        namespace=namespace, name=cm_pod_spec_name)

    sa_tpl = create_sa(v1, cm, spec, ns, name_suffix, logger=logger)
    if sa_tpl:
        kopf.adopt(sa_tpl, owner=body)
        logger.info(f"Created service account")

    role_tpl = create_role(v1rbac, cm, spec, ns, name_suffix, logger=logger)
    if role_tpl:
        kopf.adopt(role_tpl, owner=body)
        logger.info(f"Created role")

    role_binding_tpl = create_role_binding(
        v1rbac, cm, spec, ns, name_suffix, logger=logger)
    if role_binding_tpl:
        kopf.adopt(role_binding_tpl, owner=body)
        logger.info(f"Created rolebinding")

    pod_tpl = create_pod(v1, cm, spec, ns, name_suffix)
    if pod_tpl:
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


def set_settings_secret_name(pod_tpl: Dict[str, Any], secret_name: str):
    """
    Set the secret volume and volume mounts from the pod.
    """
    spec = pod_tpl["spec"]
    for volume in spec["volumes"]:
        if volume["name"] == "chaostoolkit-settings":
            volume["secret"]["secretName"] = secret_name
            break


def create_sa(api: client.CoreV1Api, configmap: Resource,
              cro_spec: ResourceChunk, ns: str, name_suffix: str,
              logger: logging.Logger):
    sa_name = cro_spec.get("serviceaccount", {}).get("name")
    if not sa_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-sa.yaml'])
        sa_name = tpl["metadata"]["name"]
        sa_name = f"{sa_name}-{name_suffix}"
        tpl["metadata"]["name"] = sa_name
        set_ns(tpl, ns)
        try:
            api.create_namespaced_service_account(body=tpl, namespace=ns)
            return tpl
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Service account '{sa_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to create service account: {str(e)}")


def create_role(api: client.RbacAuthorizationV1Api, configmap: Resource,
                cro_spec: ResourceChunk, ns: str, name_suffix: str,
                logger: logging.Logger):
    role_name = cro_spec.get("role", {}).get("name")
    if not role_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-role.yaml'])
        role_name = tpl["metadata"]["name"]
        role_name = f"{role_name}-{name_suffix}"
        tpl["metadata"]["name"] = role_name
        set_ns(tpl, ns)
        try:
            api.create_namespaced_role(body=tpl, namespace=ns)
            return tpl
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Role '{role_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to create role: {str(e)}")


def create_role_binding(api: client.RbacAuthorizationV1Api,
                        configmap: Resource, cro_spec: ResourceChunk, ns: str,
                        name_suffix: str, logger: logging.Logger):
    role_name = cro_spec.get("role", {}).get("name")
    if not role_name:
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


def create_pod(api: client.CoreV1Api, configmap: Resource,
               cro_spec: ResourceChunk, ns: str, name_suffix: str):
    pod_spec = cro_spec.get("pod", {})

    # did the user supply their own pod spec?
    tpl = pod_spec.get("template")

    # if not, let's use the default one
    if not tpl:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-pod.yaml'])
        image_name = pod_spec.get("image", {}).get(
            "name", "chaostoolkit/chaostoolkit")
        env_cm_name = pod_spec.get("env", {}).get(
            "configMapName", "chaostoolkit-env")
        env_cm_enabled = pod_spec.get("env", {}).get("enabled", True)
        settings_secret_enabled = pod_spec.get("settings", {}).get(
            "enabled", False)
        settings_secret_name = pod_spec.get("settings", {}).get(
            "secretName", "chaostoolkit-settings")

        set_image_name(tpl, image_name)

        if not env_cm_enabled:
            remove_env_config_map(tpl)
        elif env_cm_name:
            set_env_config_map_name(tpl, env_cm_name)

        if not settings_secret_enabled:
            remove_settings_secret(tpl)
        elif settings_secret_name:
            set_settings_secret_name(tpl, settings_secret_name)

    set_ns(tpl, ns)
    set_pod_name(tpl, name_suffix=name_suffix)
    set_sa_name(tpl, name_suffix=name_suffix)

    api.create_namespaced_pod(body=tpl, namespace=ns)
    return tpl
