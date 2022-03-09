import hashlib
import logging
from typing import Any, Dict, List, Union, Optional

import kopf
from kopf._cogs.structs import bodies
from kubernetes import client, config  # noqa: W0611
from kubernetes.client.rest import ApiException
import yaml


Resource = Dict[str, Any]
ResourceChunk = Dict[str, Any]


@kopf.on.create('chaostoolkit.org', 'v1', 'chaosexperiments')  # noqa: C901
async def create_chaos_experiment(  # noqa: C901
        meta: ResourceChunk, body: bodies.Body, spec: ResourceChunk,
        namespace: str, logger: logging.Logger, **kwargs) -> None:
    """
    Create a new pod running a Chaos Toolkit instance until it terminates.

    If experiment is scheduled, create a new cronJob that will
    periodically create a Chaos Toolkit instance.
    """
    v1 = client.CoreV1Api()
    v1rbac = client.RbacAuthorizationV1Api()
    v1policy = client.PolicyV1beta1Api()
    v1cron = client.BatchV1Api()

    name_suffix = generate_name_suffix(body)
    logger.info(f"Suffix for resource names will be '-{name_suffix}'")

    cm = await get_config_map(v1, spec, namespace)
    psp = await get_default_psp(v1policy)
    ns, _ = await create_ns(v1, cm, spec)
    await create_sa(v1, cm, spec, ns, name_suffix)
    await create_role(v1rbac, cm, spec, ns, name_suffix, psp=psp)
    await create_role_binding(v1rbac, cm, spec, ns, ns, name_suffix)
    await bind_role_to_namespaces(v1rbac, cm, spec, ns, name_suffix, psp=psp)
    _, cm_was_created = await create_experiment_env_config_map(
        v1, ns, spec, name_suffix)

    schedule = spec.get("schedule", {})
    if schedule:
        if schedule.get('kind').lower() == 'cronjob':
            # when schedule defined, we cannot create the pod directly,
            # we must create a cronJob with the pod definition
            pod_tpl = await create_pod(
                v1, cm, spec, ns, name_suffix, meta, apply=False,
                cm_was_created=cm_was_created)
            if pod_tpl:
                await create_cron_job(
                    v1cron, cm, spec, ns, name_suffix, meta,
                    pod_tpl=pod_tpl)
    else:
        # create pod for running experiment right away
        pod_tpl = await create_pod(
            v1, cm, spec, ns, name_suffix, meta, cm_was_created=cm_was_created)


@kopf.on.delete('chaostoolkit.org', 'v1', 'chaosexperiments')  # noqa: C901
async def delete_chaos_experiment(  # noqa: C901
        meta: ResourceChunk, body: bodies.Body, spec: ResourceChunk,
        namespace: str, logger: logging.Logger, **kwargs) -> None:
    v1 = client.CoreV1Api()
    v1rbac = client.RbacAuthorizationV1Api()
    v1cron = client.BatchV1Api()

    ns = spec.get("namespace", "chaostoolkit-run")
    name_suffix = generate_name_suffix(body)
    logger.info(f"Deleting objects with suffix '-{name_suffix}' in ns '{ns}'")

    try:
        cm = await get_config_map(v1, spec, namespace)
        schedule = spec.get("schedule", {})
        if schedule:
            if schedule.get('kind').lower() == 'cronjob':
                await delete_cron_job(v1cron, cm, spec, ns, name_suffix)
        else:
            await delete_pod(v1, cm, spec, ns, name_suffix)
        await delete_experiment_env_config_map(
            v1, ns, spec.get("pod", {}).get("env", {}).get(
                "configMapName", "chaostoolkit-env"), name_suffix)
        await unbind_role_from_namespaces(v1rbac, cm, spec, ns, name_suffix)
        await delete_role_binding(
            v1rbac, cm, spec, ns, name_suffix)
        await delete_role(v1rbac, cm, spec, ns, name_suffix)
        await delete_sa(v1, cm, spec, ns, name_suffix)
    except Exception:
        logger.error(
            f"Failed to delete objects with suffix '-{name_suffix}' in "
            f"ns '{ns}'", exc_info=True)


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


def generate_name_suffix(body: bodies.Body, suffix_length: int = 5) -> str:
    return hashlib.blake2b(
        body["metadata"]["uid"].encode('utf-8'), digest_size=5).hexdigest()


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


def set_cm_env_name(pod_tpl: Dict[str, Any], name: str = None,
                    name_suffix: str = None,
                    cm_was_created: bool = True) -> str:
    """
    Set the config map ref name of the pod
    """
    cm_name = name
    if cm_was_created:
        cm_name = f"{cm_name}-{name_suffix}"
    for container in pod_tpl["spec"]["containers"]:
        if container["name"] == "chaostoolkit":
            for ef in container.get("envFrom", []):
                if "configMapRef" in ef:
                    cmr = ef["configMapRef"]
                    if cmr["name"] == name:
                        cmr["name"] = cm_name


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


def set_experiment_config_map_name(pod_tpl: Dict[str, Any], cm_name: str,
                                   experiment_file: str = "experiment.json"):
    """
    Set the experiment config map volume and volume mounts from the pod.
    """
    spec = pod_tpl["spec"]
    for volume in spec["volumes"]:
        if volume["name"] == "chaostoolkit-experiment":
            volume["configMap"]["name"] = cm_name
            break

    for container in spec["containers"]:
        if container["name"] == "chaostoolkit":
            for e in container["env"]:
                if e["name"] == "EXPERIMENT_PATH":
                    e["value"] = f"/home/svc/{experiment_file}"
                    break

            for mount in container["volumeMounts"]:
                if mount["name"] == "chaostoolkit-experiment":
                    mount["mountPath"] = f"/home/svc/{experiment_file}"
                    mount["subPath"] = experiment_file
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


def set_rule_psp_name(rule_tpl: Dict[str, Any], name: str) -> None:
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


def set_cron_job_schedule(cron_tpl: Dict[str, Any],
                          schedule: str) -> None:
    """
    Set the cron job schedule, if specifed, otherwise leaves default
    schedule
    """
    if not schedule:
        return

    cron_spec = cron_tpl.setdefault("spec", {})
    cron_spec["schedule"] = schedule


def set_cron_job_template_spec(
        cron_tpl: Dict[str, Any], tpl_spec: Dict[str, Any]) -> None:
    """
    Set the spec for the cron job template
    """
    cron_spec = cron_tpl.setdefault("spec", {})
    _tpl = cron_spec.setdefault(
        "jobTemplate", {}).setdefault(
        "spec", {}).setdefault(
        "template", {})
    _tpl["spec"] = tpl_spec


async def create_experiment_env_config_map(v1: client.CoreV1Api(),
                                           namespace: str,
                                           spec: Dict[str, Any],
                                           name_suffix: str = None):
    """
    Create the default configmap to hold experiment environment variables,
    in case it wasn't already created by the user.

    If it already exists, we do not return it so that the operator does not
    take its ownership.
    """
    logger = logging.getLogger('kopf.objects')
    created = False

    try:
        cm = v1.read_namespaced_config_map(
            namespace=namespace, name="chaostoolkit-env")
        logger.info("Reusing existing default 'chaostoolkit-env' configmap")
    except ApiException:
        spec_env = spec.get("pod", {}).get("env", {})
        cm_name = spec_env.get("configMapName", "chaostoolkit-env")
        cm_name = f"chaostoolkit-env-{name_suffix}"
        body = client.V1ConfigMap(metadata=client.V1ObjectMeta(name=cm_name))

        logger.info(f"Creating default '{cm_name}' configmap")
        try:
            cm = v1.create_namespaced_config_map(namespace, body)
            created = True
        except ApiException as e:
            raise kopf.PermanentError(
                f"Failed to create experiment configmap: {str(e)}")

    return cm, created


async def delete_experiment_env_config_map(v1: client.CoreV1Api(),
                                           namespace: str,
                                           name: str = "chaostoolkit-env",
                                           name_suffix: str = None):
    logger = logging.getLogger('kopf.objects')
    name = f"{name}-{name_suffix}"
    logger.info("Deleting '{name}' configmap")
    try:
        return v1.delete_namespaced_config_map(
            name=name, namespace=namespace)
    except ApiException:
        logger.error(
            f"Failed to delete experiment configmap '{name}'", exc_info=True)


async def get_config_map(v1: client.CoreV1Api(), spec: Dict[str, Any],
                         namespace: str):
    cm_pod_spec_name = spec.get("template", {}).get(
        "name", "chaostoolkit-resources-templates")
    cm = v1.read_namespaced_config_map(
        namespace=namespace, name=cm_pod_spec_name)
    return cm


async def get_default_psp(v1: client.PolicyV1beta1Api,
                          name: str = 'chaostoolkit-run'
                          ) -> Optional[client.V1beta1PodSecurityPolicy]:
    """
    Get the default PodSecurityPolicy for the CTK pod,
    if the CRD is installed with podsec variant.
    """
    logger = logging.getLogger('kopf.objects')
    try:
        return v1.read_pod_security_policy(name=name)
    except ApiException:
        logger.info("Default PSP for chaostoolkit not found.")


async def create_ns(api: client.CoreV1Api, configmap: Resource,
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
        r = api.create_namespace(body=tpl)
        return ns_name, r
    except ApiException as e:
        if e.status == 409:
            logger.info(
                f"Namespace '{ns_name}' already exists. Let's continue...",
                exc_info=False)
            return ns_name, None
        else:
            raise kopf.PermanentError(
                f"Failed to create namespace: {str(e)}")


async def create_sa(api: client.CoreV1Api, configmap: Resource,
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
            return api.create_namespaced_service_account(
                body=tpl, namespace=ns)
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Service account '{sa_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to create service account: {str(e)}")


async def delete_sa(api: client.CoreV1Api, configmap: Resource,
                    cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    sa_name = cro_spec.get("serviceaccount", {}).get("name")
    if not sa_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-sa.yaml'])
        sa_name = tpl["metadata"]["name"]
        sa_name = f"{sa_name}-{name_suffix}"
        logger.debug(f"Deleting service account: {sa_name}")
        try:
            return api.delete_namespaced_service_account(
                name=sa_name, namespace=ns)
        except ApiException:
            logger.error(
                f"Failed to delete service account '{sa_name}'", exc_info=True)


async def create_role(api: client.RbacAuthorizationV1Api, configmap: Resource,
                      cro_spec: ResourceChunk, ns: str, name_suffix: str,
                      psp: client.V1beta1PodSecurityPolicy = None):
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

            tpl["rules"].append(psp_rule)
            set_rule_psp_name(psp_rule, psp.metadata.name)

        logger.debug(f"Creating role with template:\n{tpl}")
        try:
            return api.create_namespaced_role(body=tpl, namespace=ns)
        except ApiException as e:
            if e.status == 409:
                logger.info(f"Role '{role_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to create role: {str(e)}")


async def delete_role(api: client.RbacAuthorizationV1Api, configmap: Resource,
                      cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    role_name = cro_spec.get("role", {}).get("name")
    if not role_name:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-role.yaml'])
        role_name = tpl["metadata"]["name"]
        role_name = f"{role_name}-{name_suffix}"
        logger.debug(f"Deleting role with template: {role_name}")
        try:
            return api.delete_namespaced_role(name=role_name, namespace=ns)
        except ApiException:
            logger.error(f"Failed to delete role '{role_name}'", exc_info=True)


async def create_role_binding(api: client.RbacAuthorizationV1Api,
                              configmap: Resource, cro_spec: ResourceChunk,
                              ns: str, sa_ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    role_bind_name = cro_spec.get("role", {}).get("bind")
    if not role_bind_name:
        tpl = yaml.safe_load(
            configmap.data['chaostoolkit-role-binding.yaml'])
        role_binding_name = tpl["metadata"]["name"]
        role_binding_name = f"{role_binding_name}-{name_suffix}"
        tpl["metadata"]["name"] = role_binding_name

        # change sa subject name
        sa_name = tpl["subjects"][0]["name"]
        sa_name = f"{sa_name}-{name_suffix}"
        tpl["subjects"][0]["name"] = sa_name

        # change sa subject namespace
        tpl["subjects"][0]["namespace"] = sa_ns

        # change role name
        role_name = cro_spec.get("role", {}).get("name")
        if not role_name:
            role_name = tpl["roleRef"]["name"]
            role_name = f"{role_name}-{name_suffix}"
        tpl["roleRef"]["name"] = role_name

        set_ns(tpl, ns)
        logger.debug(f"Creating role binding with template:\n{tpl}")
        try:
            return api.create_namespaced_role_binding(body=tpl, namespace=ns)
        except ApiException as e:
            if e.status == 409:
                logger.info(
                    f"Role binding '{role_binding_name}' already exists.")
            else:
                raise kopf.PermanentError(
                    f"Failed to bind to role: {str(e)}")


async def bind_role_to_namespaces(api: client.RbacAuthorizationV1Api,
                                  configmap: Resource, cro_spec: ResourceChunk,
                                  ns: str, name_suffix: str,
                                  psp: client.V1beta1PodSecurityPolicy = None):
    """
    Binds the role to other namespaces so the experiment can perform ops
    in them.
    """
    bind_ns = cro_spec.get("role", {}).get("binds_to_namespaces", [])
    if not bind_ns:
        return

    for bind in bind_ns:
        await create_role(api, configmap, cro_spec, bind, name_suffix, psp)
        await create_role_binding(
            api, configmap, cro_spec, bind, ns, name_suffix)


async def unbind_role_from_namespaces(api: client.RbacAuthorizationV1Api,
                                      configmap: Resource,
                                      cro_spec: ResourceChunk, ns: str,
                                      name_suffix: str):
    """
    Unbinds the role from other namespaces so the experiment can perform ops
    in them.
    """
    bind_ns = cro_spec.get("role", {}).get("binds_to_namespaces", [])
    if not bind_ns:
        return

    for bind in bind_ns:
        await delete_role(api, configmap, cro_spec, bind, name_suffix)
        await delete_role_binding(api, configmap, cro_spec, bind, name_suffix)


async def delete_role_binding(api: client.RbacAuthorizationV1Api,
                              configmap: Resource, cro_spec: ResourceChunk,
                              ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    role_bind_name = cro_spec.get("role", {}).get("bind")
    if not role_bind_name:
        tpl = yaml.safe_load(
            configmap.data['chaostoolkit-role-binding.yaml'])
        role_binding_name = tpl["metadata"]["name"]
        role_binding_name = f"{role_binding_name}-{name_suffix}"
        logger.debug(f"Deleting role binding: {role_binding_name}")
        try:
            return api.delete_namespaced_role_binding(
                name=role_binding_name, namespace=ns)
        except ApiException:
            logger.error(
                f"Failed to delete role binding '{role_binding_name}'",
                exc_info=True)


async def create_pod(api: client.CoreV1Api, configmap: Resource,  # noqa: C901
                    cro_spec: ResourceChunk, ns: str, name_suffix: str,
                    cro_meta: ResourceChunk, *, apply: bool = True,
                    cm_was_created: bool = True):
    logger = logging.getLogger('kopf.objects')

    pod_spec = cro_spec.get("pod", {})
    sa_name = cro_spec.get("serviceaccount", {}).get("name")
    env_cm_name = pod_spec.get("env", {}).get(
        "configMapName", "chaostoolkit-env")

    # did the user supply their own pod spec?
    tpl = pod_spec.get("template")

    # if not, let's use the default one
    if not tpl:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-pod.yaml'])
        image_name = pod_spec.get("image")
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
        experiment_config_map_file_name = pod_spec.get("experiment", {}).get(
            "configMapExperimentFileName", "experiment.json")
        cmd_args = pod_spec.get("chaosArgs", [])

        # if image name is not given in CRO,
        # we keep the one defined by default in pod template from configmap
        if image_name:
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
                "Experiment config map named "
                f"'{experiment_config_map_name}'")
            set_experiment_config_map_name(
                tpl, experiment_config_map_name,
                experiment_config_map_file_name)
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
    set_cm_env_name(
        tpl, env_cm_name, name_suffix=name_suffix,
        cm_was_created=cm_was_created)
    kopf.label(tpl, labels=cro_meta.get('labels', {}))

    if apply:
        logger.debug(f"Creating pod with template:\n{tpl}")
        pod = api.create_namespaced_pod(body=tpl, namespace=ns)
        logger.info(f"Pod {pod.metadata.self_link} created in ns '{ns}'")
        return pod

    return tpl


async def delete_pod(api: client.CoreV1Api, configmap: Resource,  # noqa: C901
                     cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')

    pod_spec = cro_spec.get("pod", {})
    tpl = pod_spec.get("template")
    if not tpl:
        tpl = yaml.safe_load(configmap.data['chaostoolkit-pod.yaml'])

    pod_name = tpl["metadata"]["name"]
    pod_name = f"{pod_name}-{name_suffix}"
    logger.debug(f"Deleting pod: {pod_name}")
    try:
        return api.delete_namespaced_pod(name=pod_name, namespace=ns)
    except ApiException:
        logger.error(f"Failed to delete pod '{pod_name}'", exc_info=True)


async def create_cron_job(api: client.BatchV1Api, configmap: Resource,
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
    kopf.label(tpl, labels=experiment_labels)
    kopf.label(tpl["spec"]["jobTemplate"], labels=experiment_labels)
    kopf.label(
        tpl["spec"]["jobTemplate"]["spec"]["template"],
        labels=experiment_labels)

    logger.debug(f"Creating cron job with template:\n{tpl}")
    cron = api.create_namespaced_cron_job(body=tpl, namespace=ns)
    logger.info(f"Cron Job '{cron.metadata.self_link}' scheduled with "
                f"pattern '{schedule}' in ns '{ns}'")

    return cron


async def delete_cron_job(api: client.BatchV1Api, configmap: Resource,
                          cro_spec: ResourceChunk, ns: str, name_suffix: str):
    logger = logging.getLogger('kopf.objects')
    tpl = yaml.safe_load(configmap.data['chaostoolkit-cronjob.yaml'])
    cron_job_name = tpl["metadata"]["name"]
    cron_job_name = f"{cron_job_name}-{name_suffix}"
    logger.debug(f"Deleting cron job: {cron_job_name}")
    try:
        return api.delete_namespaced_cron_job(name=cron_job_name, namespace=ns)
    except ApiException:
        logger.error(
            f"Failed to cron job '{cron_job_name}'", exc_info=True)
