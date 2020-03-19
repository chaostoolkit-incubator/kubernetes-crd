from typing import List

import yaml


def test_create_chaos_experiment_in_default_ns(generic: List['Resource']):
    resource = generic[0]
    assert resource["apiVersion"] == "v1"
    assert resource["kind"] == "Namespace"
    assert resource["metadata"]["name"] == "chaostoolkit-crd"
    assert resource["metadata"]["labels"] == {
        "app": "chaostoolkit-crd",
        "provider": "chaostoolkit",
        "role": "chaosengineering"
    }

    resource = generic[1]
    assert resource["apiVersion"] == "v1"
    assert resource["kind"] == "Namespace"
    assert resource["metadata"]["name"] == "chaostoolkit-run"

    resource = generic[2]
    assert resource["apiVersion"] == "apiextensions.k8s.io/v1beta1"
    assert resource["kind"] == "CustomResourceDefinition"
    assert resource["metadata"]["name"] == "chaosexperiments.chaostoolkit.org"
    assert resource["metadata"]["labels"] == {
        "app": "chaostoolkit-crd",
        "provider": "chaostoolkit",
        "role": "chaosengineering"
    }
    assert resource["spec"]["scope"] == "Namespaced"
    assert resource["spec"]["group"] == "chaostoolkit.org"
    assert resource["spec"]["versions"] == [
        {
            "name": "v1",
            "served": True,
            "storage": True
        }
    ]
    assert resource["spec"]["names"] == {
        "kind": "ChaosToolkitExperiment",
        "plural": "chaosexperiments",
        "singular": "chaosexperiment",
        "shortNames": ["ctk", "ctks"]
    }
    
    resource = generic[3]
    assert resource["apiVersion"] == "v1"
    assert resource["kind"] == "ServiceAccount"
    assert resource["metadata"]["name"] == "chaostoolkit-crd"
    assert resource["metadata"]["namespace"] == "chaostoolkit-crd"
    assert resource["metadata"]["labels"] == {
        "app": "chaostoolkit-crd",
        "provider": "chaostoolkit",
        "role": "chaosengineering"
    }

    resource = generic[4]
    assert resource["apiVersion"] == "v1"
    assert resource["kind"] == "ConfigMap"
    assert resource["metadata"]["name"] == "chaostoolkit-resources-templates"
    assert resource["metadata"]["namespace"] == "chaostoolkit-crd"
    assert resource["metadata"]["labels"] == {
        "app": "chaostoolkit-crd",
        "provider": "chaostoolkit",
        "role": "chaosengineering"
    }
    ctk_ns = yaml.safe_load(resource["data"]["chaostoolkit-ns.yaml"])
    assert ctk_ns["apiVersion"] == "v1"
    assert ctk_ns["kind"] == "Namespace"
    assert ctk_ns["metadata"] == {
        "name": "chaostoolkit-run"
    }

    ctk_role = yaml.safe_load(resource["data"]["chaostoolkit-role.yaml"])
    assert ctk_role["apiVersion"] == "rbac.authorization.k8s.io/v1"
    assert ctk_role["kind"] == "Role"
    assert ctk_role["metadata"] == {
        "name": "chaostoolkit-experiment"
    }
    assert ctk_role["rules"] == [
        {
            "apiGroups": [""],
            "resources": ["pods"],
            "verbs": ["create", "get", "delete", "list"]
        }
    ]

    ctk_rolebinding = yaml.safe_load(
        resource["data"]["chaostoolkit-role-binding.yaml"])
    assert ctk_rolebinding["apiVersion"] == "rbac.authorization.k8s.io/v1"
    assert ctk_rolebinding["kind"] == "RoleBinding"
    assert ctk_rolebinding["metadata"] == {
        "name": "chaostoolkit-experiment"
    }
    assert ctk_rolebinding["roleRef"] == {
        "apiGroup": "rbac.authorization.k8s.io",
        "kind": "Role",
        "name": "chaostoolkit-experiment"
    }
    assert ctk_rolebinding["subjects"] == [{
        "kind": "ServiceAccount",
        "name": "chaostoolkit"
    }]
