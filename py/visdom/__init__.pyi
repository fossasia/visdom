# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Text, Tuple, Union

### Type aliases for commonly-used types.
# For optional 'options' parameters.
# The options parameters can be strongly-typed with the proposed TypedDict type once that is incorporated into the standard.
# See  http://mypy.readthedocs.io/en/latest/more_types.html#typeddict.
_OptOps = Optional[Mapping[Text, Any]]
_OptStr = Optional[Text]  # For optional string parameters, like 'window' and 'env'.

# For the list of environments to compare. Spelled out rather than Sequence[Text]
# because a bare str is itself a Sequence[str]: 'compare_experiments' rejects one
# at runtime, so a checker must not accept it here.
_EnvIds = Union[List[Text], Tuple[Text, ...]]

# The decoded JSON reply of the experiment endpoints.
_ExperimentReply = Mapping[Text, Any]
_TagMap = Mapping[Text, Text]

# The reply of the experiment endpoints that only answer questions. An offline
# client has no server to ask, so those hand back None rather than a reply.
_ExperimentQueryReply = Optional[_ExperimentReply]

# No widely-deployed stubs exist at the moment for torch or numpy. When they are available, the correct type of the tensor-like inputs
# to the plotting commands should be
# Tensor = Union[torch.Tensor, numpy.ndarray, List]
# For now, we fall back to 'Any'.
Tensor = Any

# The return type of 'Visdom._send', which is turn is also the return type of most of the the plotting commands.
# It technically can return a union of several different types, but in normal usage,
# it will return a single string. We only type it as such to prevent the need for users to unwrap the union.
# See https://github.com/python/mypy/issues/1693.
_SendReturn = Text

# A decoded server event, as handed to a registered event handler. The handler's
# return value is discarded, so it is deliberately unconstrained.
_Event = Mapping[Text, Any]
_EventHandler = Callable[[_Event], Any]

# Event handlers are keyed by the (env, target) pair they were registered under.
# 'env' is None for a handler registered for every environment.
_EventKey = Tuple[_OptStr, Text]

class Visdom:
    # Public attributes. Callers read 'env' to see the environment new windows
    # land in and assign it to change that; the rest are the connection state the
    # documented patterns poll ('while not vis.check_connection()' and friends).
    env: Text
    env_list: Set[Text]
    win_data: Dict[Text, Any]
    offline: bool
    use_socket: bool
    socket_alive: bool
    use_preflight_checks: bool
    event_handlers: Dict[_EventKey, List[_EventHandler]]

    def __init__(
        self,
        server: Text = ...,
        endpoint: Text = ...,
        port: int = ...,
        base_url: Text = ...,
        ipv6: bool = ...,
        http_proxy_host: _OptStr = ...,
        http_proxy_port: Optional[int] = ...,
        env: Text = ...,
        *,
        raise_exceptions: Optional[bool] = ...,
        use_incoming_socket: bool = ...,
        log_to_filename: _OptStr = ...,
        username: _OptStr = ...,
        password: _OptStr = ...,
        proxies: Optional[Mapping[Text, Text]] = ...,
        offline: bool = ...,
        use_polling: bool = ...,
        session_idle_timeout: Union[int, float] = ...,
        session_idle_check_interval: Union[int, float] = ...,
        ssl_verify: Optional[Union[bool, Text]] = ...,
        use_preflight_checks: bool = ...,
    ) -> None: ...
    def setup_socket(self, polling: bool = ...) -> None: ...
    def setup_polling(self) -> None: ...
    def register_event_handler(
        self, handler: _EventHandler, target: Text, env: _OptStr = ...
    ) -> None: ...
    def clear_event_handlers(self, target: Text, env: _OptStr = ...) -> None: ...
    def _send(
        self,
        msg: Any,
        endpoint: Text = ...,
        quiet: bool = ...,
        from_log: bool = ...,
        create: bool = ...,
        default_eid: bool = ...,
    ) -> _SendReturn: ...
    def save(self, envs: List[Text]) -> _SendReturn: ...
    def close(self, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
    def experiment(
        self,
        name: _OptStr = ...,
        params: _OptOps = ...,
        tags: _OptOps = ...,
        description: _OptStr = ...,
        env: _OptStr = ...,
    ) -> Mapping[Text, Any]: ...
    def log_metrics(
        self,
        metrics: Mapping[Text, Any],
        step: Optional[int] = ...,
        env: _OptStr = ...,
    ) -> Mapping[Text, Any]: ...
    def finish_experiment(
        self, status: Text = ..., env: _OptStr = ...
    ) -> Mapping[Text, Any]: ...
    def set_tags(
        self,
        tags: _TagMap,
        env: _OptStr = ...,
        append: bool = ...,
    ) -> _TagMap: ...
    def get_tags(self, env: _OptStr = ...) -> _TagMap: ...
    def search_experiments(
        self,
        query: _OptStr = ...,
        limit: Optional[int] = ...,
        offset: int = ...,
        sort_by: _OptStr = ...,
        descending: bool = ...,
    ) -> _ExperimentQueryReply: ...
    def compare_experiments(self, env_ids: _EnvIds) -> _ExperimentQueryReply: ...
    def suggest_experiment(
        self, params: _OptOps = ..., env: _OptStr = ...
    ) -> _ExperimentQueryReply: ...
    def hparams(
        self,
        query: _OptStr = ...,
        env_ids: Optional[_EnvIds] = ...,
        mode: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def update_hparams(
        self,
        win: Text,
        query: _OptStr = ...,
        env_ids: Optional[_EnvIds] = ...,
        mode: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def get_window_data(
        self, win: _OptStr = ..., env: _OptStr = ...
    ) -> _SendReturn: ...
    def set_window_data(
        self, data: Any, win: _OptStr = ..., env: _OptStr = ...
    ) -> _SendReturn: ...
    def delete_env(self, env: Text) -> _SendReturn: ...
    def delete_envs(self, env_list: _EnvIds) -> List[_SendReturn]: ...
    def fork_env(self, prev_eid: Text, eid: Text) -> _SendReturn: ...
    def get_env_list(self) -> List[Text]: ...
    def get_env_state(self, env: Text) -> Optional[Mapping[Text, Any]]: ...
    def win_exists(self, win: Text, env: _OptStr = ...) -> Optional[bool]: ...
    def check_connection(self, timeout_seconds: Union[int, float] = ...) -> bool: ...
    def replay_log(self, log_filename: Text) -> None: ...
    def text(
        self,
        text: Text,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        append: bool = ...,
    ) -> _SendReturn: ...
    def svg(
        self,
        svgstr: _OptStr = ...,
        svgfile: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def matplot(
        self, plot: Any, opts: _OptOps = ..., env: _OptStr = ..., win: _OptStr = ...
    ) -> _SendReturn: ...
    def save_plotly_figure(
        self, figure: Any, filepath: Text, **kwargs: Any
    ) -> None: ...
    def plotlyplot(
        self,
        figure: Any,
        win: _OptStr = ...,
        env: _OptStr = ...,
        save_path: _OptStr = ...,
        save_kwargs: Optional[Mapping[Text, Any]] = ...,
    ) -> _SendReturn: ...
    def image(
        self, img: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    def image_select(
        self, win: Text, selected: int, env: _OptStr = ...
    ) -> _SendReturn: ...
    def image_heatmap(
        self,
        img: Tensor,
        heatmap: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def update_image_slider(
        self, win: Text, index: Union[int, float], env: _OptStr = ...
    ) -> _SendReturn: ...
    def images(
        self,
        tensor: Tensor,
        nrow: int = ...,
        padding: int = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def audio(
        self,
        tensor: Tensor,
        audiofile: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def video(
        self,
        tensor: Tensor = ...,
        dim: Text = ...,
        videofile: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def update_window_opts(
        self, win: Text, opts: Mapping[Text, Any], env: _OptStr = ...
    ) -> _SendReturn: ...
    def learning_curve(
        self,
        metrics: Mapping[Text, Any],
        step: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        update: _OptStr = ...,
    ) -> _SendReturn: ...
    def scatter(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
    ) -> _SendReturn: ...
    def line(
        self,
        Y: Tensor,
        X: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
        Z: Optional[Tensor] = ...,
        is3d: bool = ...,
    ) -> _SendReturn: ...
    def heatmap(
        self,
        X: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        update: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def bar(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def histogram(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    def histogram2d(
        self,
        X: Tensor,
        Y: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def boxplot(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    def roc_curve(
        self,
        y_true: Optional[Tensor] = ...,
        y_score: Optional[Tensor] = ...,
        fpr: Optional[Tensor] = ...,
        tpr: Optional[Tensor] = ...,
        pos_label: Union[int, float] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def pr_curve(
        self,
        y_true: Optional[Tensor] = ...,
        y_score: Optional[Tensor] = ...,
        precision: Optional[Tensor] = ...,
        recall: Optional[Tensor] = ...,
        pos_label: Union[int, float] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def confusion_matrix(
        self,
        y_true: Optional[Tensor] = ...,
        y_pred: Optional[Tensor] = ...,
        cm: Optional[Tensor] = ...,
        labels: Optional[list] = ...,
        normalize: Optional[str] = ...,
        update: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def surf(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    def contour(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    def quiver(
        self,
        X: Tensor,
        Y: Tensor,
        gridX: Optional[Tensor] = ...,
        gridY: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def stem(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def pie(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    def mesh(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def sankey(
        self,
        source: Tensor,
        target: Tensor,
        value: Tensor,
        labels: Optional[List] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def graph(
        self,
        edges: List,
        edgeLabels: Optional[List] = ...,
        nodeLabels: Optional[List] = ...,
        opts: _OptOps = ...,
        env: _OptStr = ...,
        win: _OptStr = ...,
    ) -> _SendReturn: ...
    def parallel_coordinates(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def violin(
        self,
        X: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def properties(
        self,
        data: List,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def html_table(
        self,
        data: List[Any],
        headers: Optional[List[Any]] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def embeddings(
        self,
        features: Tensor,
        labels: Tensor,
        data_getter: Optional[Callable[[int], Any]] = ...,
        data_type: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def sunburst(
        self,
        labels: Tensor,
        parents: Tensor,
        values: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def dual_axis_lines(
        self,
        X: Optional[Tensor] = ...,
        Y1: Optional[Tensor] = ...,
        Y2: Optional[Tensor] = ...,
        opts: _OptOps = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
    ) -> _SendReturn: ...
    def table(
        self,
        data: List[Any],
        headers: Optional[List[Any]] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
