import os


def repo_root():
    return os.path.dirname(os.path.abspath(__file__))


def get_project_id():
    return str(os.environ.get("GA_PROJECT_ID", "") or "").strip()


def get_project_name():
    return str(os.environ.get("GA_PROJECT_NAME", "") or "").strip()


def get_model_responses_root(base_dir=None):
    base_dir = base_dir or repo_root()
    return os.path.join(base_dir, "temp", "model_responses")


def get_model_responses_dir(base_dir=None, project_id=None):
    project_id = get_project_id() if project_id is None else str(project_id or "").strip()
    root = get_model_responses_root(base_dir)
    return os.path.join(root, project_id) if project_id else root


def get_model_response_globs(base_dir=None, project_id=None):
    return (os.path.join(get_model_responses_dir(base_dir, project_id), "model_responses_*.txt"),)


def get_model_response_log_path(pid=None, base_dir=None, project_id=None):
    pid = os.getpid() if pid is None else pid
    return os.path.join(get_model_responses_dir(base_dir, project_id), f"model_responses_{pid}.txt")
