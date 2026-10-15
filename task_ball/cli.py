"""Command-line task operations without importing the desktop toolkit."""

from collections.abc import Sequence

from .storage import AppPaths, load_tasks, new_task, save_tasks


def _print_usage() -> None:
    print("用法: python task_floating_ball.py add <任务内容>")
    print("      python task_floating_ball.py list")
    print("      python task_floating_ball.py del <序号>")


def run_cli(argv: Sequence[str], paths: AppPaths) -> int:
    """Handle an argv including the script name, returning a process exit code."""
    if len(argv) < 2:
        _print_usage()
        return 1
    cmd = argv[1]
    if cmd in ("-h", "--help"):
        _print_usage()
        return 0

    tasks = load_tasks(paths.tasks)
    if cmd == "add":
        text = " ".join(argv[2:]).strip()
        if not text:
            print("用法: python task_floating_ball.py add <任务内容>")
            return 1
        tasks.append(new_task(text))
        save_tasks(paths.tasks, tasks)
        print("已添加: " + text)
        return 0
    if cmd == "list":
        if not tasks:
            print("(暂无任务)")
            return 0
        for index, task in enumerate(tasks, 1):
            print("%d. %s" % (index, task["text"]))
        return 0
    if cmd == "del":
        try:
            index = int(argv[2]) - 1
        except (IndexError, ValueError):
            print("用法: python task_floating_ball.py del <序号>")
            return 1
        if not 0 <= index < len(tasks):
            print("序号超出范围，共 %d 条（先 list 查看）" % len(tasks))
            return 1
        target = tasks.pop(index)
        save_tasks(paths.tasks, tasks)
        print("已删除: " + target["text"])
        return 0
    print("未知命令: " + cmd)
    return 1
