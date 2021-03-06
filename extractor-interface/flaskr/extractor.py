from flask import (
    Blueprint, render_template
)

import subprocess
import shlex
import shutil
import os
import json
import git
from git import GitCommandError


bp = Blueprint('extractor', __name__)
ws = Blueprint(r'extractor_ws', __name__)


# get the name of a git repository
def get_repo_basename(repository):
    repo_name = repository[repository.rfind('/') + 1:]

    if not repo_name:
        url = repository[:-1]
        repo_name = url[url.rfind('/') + 1:]

    if repo_name.find('.git') != -1:
        repo_name = repo_name[:repo_name.rfind('.')]

    return repo_name


# create a message that should be sent via the websocket connection
def create_message(message_type, message):
    return json.dumps({'type': message_type, 'data': message})


# use git ls-remote to check if the link to the repository is valid and the repository is public
def check_remote_repository(repository):
    try:
        g = git.cmd.Git()
        g.ls_remote(repository)
        return True
    except GitCommandError:
        return False


# check if some of the fields are empty and if the repository is available
def validate_form_fields(repository, package, name):
    error = None

    if not repository or not package or not name:
        error = 'Please fill out all form fields.'
    elif not check_remote_repository(repository):
        error = 'The repository could not be found. ' \
                'Please ensure that the link is valid and the repository is public'

    return error


def parse_values(fields):
    repository = fields['repository']
    package = fields['package']
    name = fields['name']

    return repository, package, name


@ws.route('/')
def websocket(ws):
    while not ws.closed:
        message = ws.receive()
        print message
        if message:
            request = json.loads(message)

            errors = {}
            for key, value in request.iteritems():
                repository, package, name = parse_values(value)
                errors[key] = validate_form_fields(repository, package, name)

            print errors
            if any(error is not None for error in errors.itervalues()):
                error_message = create_message('error_event', errors)
                ws.send(error_message)
            else:
                errors = {}
                models = {}

                for key, value in request.iteritems():
                    repository, package, name = parse_values(value)
                    shell_command = '/bin/bash ' + os.environ['HAROS_RUNNER'] + ' ' + repository + ' ' + package + ' ' + name

                    extractor_process = subprocess.Popen(shlex.split(shell_command), stdout=subprocess.PIPE,
                                                         stderr=subprocess.STDOUT,
                                                         bufsize=1)

                    for line in iter(extractor_process.stdout.readline, ''):
                        run_message = create_message('run_event', str(line))
                        ws.send(run_message)
                        print line

                    extractor_process.wait()

                    current_model = None

                    try:
                        repo_name = get_repo_basename(repository)
                        shutil.rmtree(os.path.join(os.environ['HAROS_SRC'], repo_name))
                    except OSError or IOError:
                        pass

                    try:
                        model_file = open(os.path.join(os.environ['MODEL_PATH'], name + '.ros'))
                        current_model = model_file.read()
                        print 'reading'
                    except OSError or IOError:
                        errors[key] = 'There was a problem with the model generation.'

                    models[key] = current_model

                    if not current_model:
                        errors[key] = 'There was a problem with the model generation.'

                ws.send(create_message('model_event', models))
                ws.send(create_message('error_event', errors))


@bp.route('/', methods=['GET'])
def get_extractor():
    return render_template('/extractor.html')