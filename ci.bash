#!/bin/bash
set -eo pipefail

function lint () {
    echo "Checking the code syntax"
    pycodestyle controller.py
}

function build () {
    return 0
}

function run-test () {
    echo "Running the tests"
    pytest
}

function build-docker () {
    echo "Building the Docker image"
    docker login -u ${DOCKER_USER_NAME} -p ${DOCKER_PWD}
    docker build -t chaostoolkit/k8scrd .

    echo "Publishing to the Docker repository"
    docker push chaostoolkit/k8scrd:latest
}

function release () {
    docker tag chaostoolkit/k8scrd:latest chaostoolkit/k8scrd:$TRAVIS_TAG
    echo "Publishing to the Docker repository"
    docker push chaostoolkit/k8scrd:$TRAVIS_TAG
}

function main () {
    lint || return 1
    build || return 1
    run-test || return 1
    build-docker || return 1

    if [[ "$TRAVIS_OS_NAME" == "linux" ]]; then
        if [[ $TRAVIS_PYTHON_VERSION =~ ^3\.5+$ ]]; then
            if [[ $TRAVIS_TAG =~ ^[0-9]+\.[0-9]+\.[0-9]+(rc[0-9]+)?$ ]]; then
                echo "Releasing tag $TRAVIS_TAG with Python $TRAVIS_PYTHON_VERSION"
                release || return 1
            fi
        fi
    fi
}

main "$@" || exit 1
exit 0
