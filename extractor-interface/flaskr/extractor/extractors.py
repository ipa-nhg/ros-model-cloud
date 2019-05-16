import os
import shlex
import shutil
import subprocess
from abc import ABCMeta, abstractmethod


from git import GitCommandError, cmd


class ExtractorRunner(object):
    __metaclass__ = ABCMeta

    # Possible errors
    REPOSITORY_NOT_FOUND = 'REPOSITORY_NOT_FOUND'
    INVALID_FIELDS = 'INVALID_FIELDS'
    NO_MODEL_GENERATED = 'NO_MODEL_GENERATED'

    @abstractmethod
    def __init__(self, repository, package, request_id):
        # Common for the launch & node extractors
        self.repository = repository
        self.package = package
        self.id = request_id

        # Path where the model files are stored
        self.model_path = os.path.join(os.environ['MODEL_PATH'], self.id)

        # Path to where the repository is cloned
        self.repo_path = os.path.join(os.environ['HAROS_SRC'], self._get_repo_basename())

    def _get_repo_basename(self):

        repo_name = self.repository[self.repository.rfind('/') + 1:]

        if not repo_name:
            url = self.repository[:-1]
            if url.endswith('/'):
                url = url[:-1]
            repo_name = url[url.rfind('/') + 1:]

        if repo_name.find('.git') != -1:
            repo_name = repo_name[:repo_name.rfind('.')]

        return repo_name

    # use git ls-remote to check if the link to the repository is valid and the repository is public
    def _check_remote_repository(self):
        try:
            g = cmd.Git()
            g.ls_remote(self.repository)
            return True
        except GitCommandError:
            return False

    # Template for the events sent by the websocket
    def _event_template(self, event_type, **kwargs):

        from routes import ws_template

        data = {'request_id': self.id}
        data.update(kwargs)
        return ws_template(event_type, data)

    def _log_event(self, message):
        return self._event_template('log', message=message)

    def _error_event(self, message):
        return self._event_template('error', message=message)

    def _model_event(self, model, file_name):
        return self._event_template('model', model=model, file=file_name)

    # check if some of the fields are empty and if the repository is available
    @abstractmethod
    def validate(self):
        if not self.repository or not self.package:
            return self._error_event(self.INVALID_FIELDS)

        if not self._check_remote_repository():
            return self._error_event(self.REPOSITORY_NOT_FOUND)

        return None

    # should be implemented by both the node & the launch extractor
    @abstractmethod
    def run_analysis(self):
        pass


class NodeExtractorRunner(ExtractorRunner):

    def __init__(self, node, **kwargs):
        ExtractorRunner.__init__(self, **kwargs)
        self.node = node

    def validate(self):
        error = super(NodeExtractorRunner, self).validate()
        if error:
            return error

        if not self.node:
            return self._error_event(self.INVALID_FIELDS)

        return None

    def run_analysis(self):

        # Create a folder where the files for the request should be stored
        if os.path.exists(self.model_path):
            shutil.rmtree(self.repo_path)

        os.mkdir(self.model_path)

        # Start the Haros runner
        shell_command = '/bin/bash ' + \
                        os.environ['HAROS_RUNNER'] + ' ' + \
                        self.repository + ' ' + self.package + ' ' + self.node + ' node ' + self.model_path

        extractor_process = subprocess.Popen(shlex.split(shell_command), stdout=subprocess.PIPE,
                                             stderr=subprocess.STDOUT,
                                             bufsize=1)

        # Send the logs
        for line in iter(extractor_process.stdout.readline, ''):
            yield self._log_event(line)
            print line

        extractor_process.wait()

        model = None

        # Delete the source repository after the extraction is done
        try:
            shutil.rmtree(self.repo_path)
        except (OSError, IOError):
            pass

        # Read the file with the model
        try:
            model_file = open(os.path.join(self.model_path, self.node + '.ros'), 'r+')
            model = model_file.read().strip()
            model_file.close()
        except (OSError, IOError):
            pass

        # Send the model or send an error if no model was found
        if model:
            yield self._model_event(model, self.node + '.ros')
        else:
            yield self._error_event(self.NO_MODEL_GENERATED)