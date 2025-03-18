from functools import partial
from itertools import chain
from multiprocessing import Pool
from typing import Callable, Any
import os
from pprint import pprint

import tqdm

from leanclient import LeanLSPClient
from leanclient import SingleFileClient


def _init_worker(project_path: str, kwargs: dict):
    global client
    if "initial_build" not in kwargs:
        kwargs["initial_build"] = False
    client = LeanLSPClient(project_path, **kwargs)


def _close_worker():
    global client
    client.close()


def _worker_task_batched_open(*args, **kwargs):
    task = kwargs["task"]
    file_paths = args[0]
    client.open_files(file_paths)
    return [task(client.create_file_client(path)) for path in file_paths]


def _worker_task(*args, **kwargs):
    return kwargs["task"](client.create_file_client(args[0]))


class LeanClientPool:
    """Parallel processing of Lean files using multiple language servers.

    Use this context manager for parallel processing of multiple Lean files.
    It is based on Python's `multiprocessing.Pool` and uses one `LeanLSPClient` per worker.

    Tasks are defined as functions with a single argument, a :class:`leanclient.file_client.SingleFileClient` instance.

    .. code-block:: python

        def hover_task(client: SingleFileClient):
            return client.get_hover(1, 1)["contents"]["value"]

        def fun_len_task(client):
            num_symbols = len(client.get_document_symbol())
            num_tokens = len(client.get_semantic_tokens())
            return num_tokens / num_symbols

    **Example use:**

    .. code-block:: python

        from leanclient import LeanClientPool

        file_paths = ["path/to/file1.lean", "path/to/file2.lean", ...]

        with LeanClientPool("path/to/project") as pool:
            results = pool.map(hover_task, file_paths)

            # Or use submit for more control
            futures = [pool.submit(fun_len_task, file) for file in file_paths]
            results2 = [fut.get() for fut in futures]

    Note:

        By default, the initial_build is turned off in all workers.
        Use the `initial_build` kwarg to turn it on.

    Args:
        project_path(str): The path to the Lean project.
        num_workers(int | None): The number of workers to use. Defaults to 70% of CPU cores.
        **kwargs: Additional arguments to pass to :class:`leanclient.client.LeanLSPClient`.
    """

    def __init__(self, project_path: str, num_workers: int | None = None, **kwargs):
        self.project_path = project_path

        if "max_opened_files" not in kwargs:
            kwargs["max_opened_files"] = 1
        self._init_args = kwargs

        self.num_workers = (
            int(os.cpu_count() * 0.7) if num_workers is None else num_workers
        )

    def __enter__(self):
        self.pool = Pool(
            processes=self.num_workers,
            initializer=_init_worker,
            initargs=(self.project_path, self._init_args),
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for _ in range(self.num_workers):
            self.pool.apply(_close_worker)
        self.pool.close()
        self.pool.join()

    def submit(self, task: Callable[[SingleFileClient], None], file_path: str) -> Any:
        """Submit an asynchronous task to the pool.

        **Example use:**

        .. code-block:: python

            with pool:
                futures = [pool.submit(task, file) for file in file_paths]
                results = [fut.get() for fut in futures]

        Args:
            task(callable): The task to execute. Must take a `SingleFileClient` as its only argument.
            file_path(str): The path to the file to process.

        Returns:
            Any: The result of the task.
        """
        return self.pool.apply_async(
            _worker_task, args=(file_path,), kwds={"task": task}
        )

    def map(
        self,
        task: Callable[[SingleFileClient], None],
        file_paths: list,
        batch_size: int = 1,
        verbose: bool = False,
    ) -> list:
        """Parallel file processing.

        See :class:`LeanClientPool` for example use.

        Note:
            `batch_size` > 1 requires initializing the pool with `max_opened_files` > 1.

        Args:
            task(callable): The task to execute. Must take a `SingleFileClient` as its only argument.
            file_paths(list): A list of file paths to process.
            batch_size(int): Batching allows the language server to open multiple files in parallel. Typically faster but requires more resources (mainly memory). Beware of large batch_sizes. Defaults to 1.
            verbose(bool): Show a progress bar. Defaults to False.

        Returns:
            list: The result of the task for each file.
        """
        if batch_size == 1:
            partial_task = partial(_worker_task, task=task)
            if not verbose:
                return self.pool.map(partial_task, file_paths)

            with tqdm.tqdm(total=len(file_paths), desc="Processing files") as pbar:
                results = []
                for result in self.pool.imap(partial_task, file_paths):
                    results.append(result)
                    pbar.update()
                return results

        batches = (
            file_paths[i : i + batch_size]
            for i in range(0, len(file_paths), batch_size)
        )
        partial_task = partial(_worker_task_batched_open, task=task)
        if not verbose:
            return list(chain.from_iterable(self.pool.map(partial_task, batches)))

        with tqdm.tqdm(total=len(file_paths), desc="Processing files") as pbar:
            results = []
            for batch_result in self.pool.imap(partial_task, batches):
                results.extend(batch_result)
                pbar.update(len(batch_result))
            return results
