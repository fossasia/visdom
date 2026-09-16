# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

# Stubs for 'visdom.async_client'.
#
# 'AsyncVisdom' builds its plotting surface at runtime: '__getattr__' wraps
# whichever 'Visdom' method the caller asked for, as long as its name is in
# '_PROXIED'. A type checker cannot see through that, so every proxied method is
# written out here as 'async def' with the signature its synchronous twin has in
# '__init__.pyi'. The two files are kept in step by 'py/tests/unit/client_stubs.py'.
#
# '__getattr__' is deliberately *not* declared: declaring it would make the
# checker accept every attribute name, which is exactly what these stubs exist
# to prevent.

import asyncio
from concurrent.futures import Future as _ConcurrentFuture
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    FrozenSet,
    List,
    Mapping,
    Optional,
    Set,
    Text,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from tornado.httpclient import AsyncHTTPClient, HTTPRequest, HTTPResponse

from visdom import (
    Tensor,
    Visdom,
    _EnvIds,
    _Event,
    _EventHandler,
    _ExperimentQueryReply,
    _OptOps,
    _OptStr,
    _SendReturn,
    _TagMap,
)

_A = TypeVar("_A", bound="AsyncVisdom")

# 'AsyncVisdom.register_event_handler' takes either kind: a plain handler runs on
# the client's dispatch thread, a coroutine one is awaited on its loop.
_AsyncEventHandler = Callable[[_Event], Awaitable[Any]]

CONNECT_TIMEOUT: float
REQUEST_TIMEOUT: int
DEFAULT_MAX_CONCURRENCY: int
HANDSHAKE_TIMEOUT: float
RECONNECT_DELAY: float
POLL_INTERVAL: float
PING_INTERVAL: float

# The names 'AsyncVisdom.__getattr__' will proxy. Every one of them appears
# below as an 'async def'.
_PROXIED: FrozenSet[Text]

def _extract_cookie(response: HTTPResponse, name: Text) -> _OptStr: ...
def _as_requests_error(error: BaseException) -> Exception: ...

class _AsyncTransport:
    server: Text
    port: int
    base_url: Text
    username: _OptStr
    password: _OptStr
    ssl_verify: Union[bool, Text]
    max_clients: int
    cookie: _OptStr
    def __init__(
        self,
        server: Text,
        port: int,
        base_url: Text = ...,
        username: _OptStr = ...,
        password: _OptStr = ...,
        ssl_verify: Union[bool, Text] = ...,
        max_clients: int = ...,
    ) -> None: ...
    @property
    def client(self) -> AsyncHTTPClient: ...
    def websocket_url(self) -> Text: ...
    def websocket_request(self) -> HTTPRequest: ...
    async def post(self, url: Text, data: _OptStr = ...) -> Text: ...
    def close(self) -> None: ...

class _AsyncBackchannel:
    name: Text
    def __init__(
        self,
        client: _BridgedVisdom,
        loop: asyncio.AbstractEventLoop,
        transport: _AsyncTransport,
    ) -> None: ...
    def start(self) -> None: ...
    def close(self) -> Optional[asyncio.Task[None]]: ...

class _AsyncWebSocket(_AsyncBackchannel): ...
class _AsyncPolling(_AsyncBackchannel): ...

class _Call:
    future: Optional[_ConcurrentFuture[Text]]
    cancelled: bool
    def __init__(self) -> None: ...

class _BridgedVisdom(Visdom):
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *args: Any,
        transport: Optional[_AsyncTransport] = ...,
        max_clients: int = ...,
        **kwargs: Any,
    ) -> None: ...
    @property
    def transport(self) -> _AsyncTransport: ...
    def run_call(
        self,
        call: _Call,
        bound: Callable[..., Any],
        args: Tuple[Any, ...],
        kwargs: Mapping[Text, Any],
    ) -> Any: ...
    def cancel_call(self, call: _Call) -> None: ...
    def close_backchannel(self) -> Optional[asyncio.Task[None]]: ...

class AsyncVisdom:
    def __init__(self, inner: _BridgedVisdom, executor: ThreadPoolExecutor) -> None: ...
    @classmethod
    async def create(
        cls: Type[_A],
        server: Text = ...,
        endpoint: Text = ...,
        port: int = ...,
        base_url: Text = ...,
        ipv6: bool = ...,
        http_proxy_host: None = ...,
        http_proxy_port: None = ...,
        env: Text = ...,
        *,
        max_concurrency: int = ...,
        transport: Optional[_AsyncTransport] = ...,
        max_clients: int = ...,
        raise_exceptions: Optional[bool] = ...,
        use_incoming_socket: bool = ...,
        log_to_filename: _OptStr = ...,
        username: _OptStr = ...,
        password: _OptStr = ...,
        offline: bool = ...,
        use_polling: bool = ...,
        session_idle_timeout: Union[int, float] = ...,
        session_idle_check_interval: Union[int, float] = ...,
        ssl_verify: Optional[Union[bool, Text]] = ...,
        use_preflight_checks: bool = ...,
    ) -> _A: ...
    def __dir__(self) -> List[Text]: ...

    # -- Passthrough state ----------------------------------------------------
    @property
    def client(self) -> _BridgedVisdom: ...
    @property
    def env(self) -> Text: ...
    @env.setter
    def env(self, value: Text) -> None: ...
    @property
    def env_list(self) -> Set[Text]: ...
    @property
    def win_data(self) -> Dict[Text, Any]: ...
    @property
    def offline(self) -> bool: ...
    @property
    def socket_alive(self) -> bool: ...
    @property
    def use_socket(self) -> bool: ...

    # -- Events ---------------------------------------------------------------
    # Registration is bookkeeping, so these stay synchronous.
    def register_event_handler(
        self,
        handler: Union[_EventHandler, _AsyncEventHandler],
        target: Text,
        env: _OptStr = ...,
    ) -> None: ...
    def clear_event_handlers(self, target: Text, env: _OptStr = ...) -> None: ...

    # -- Lifecycle ------------------------------------------------------------
    async def shutdown(self) -> None: ...
    async def __aenter__(self: _A) -> _A: ...
    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> bool: ...

    # -- The proxied 'Visdom' surface -----------------------------------------
    # Generated from the matching entries in 'visdom/__init__.pyi'; every name
    # here is in '_PROXIED' and every name in '_PROXIED' is here.
    async def save(self, envs: List[Text]) -> _SendReturn: ...
    async def close(self, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
    async def experiment(
        self,
        name: _OptStr = ...,
        params: _OptOps = ...,
        tags: _OptOps = ...,
        description: _OptStr = ...,
        env: _OptStr = ...,
    ) -> Mapping[Text, Any]: ...
    async def log_metrics(
        self,
        metrics: Mapping[Text, Any],
        step: Optional[int] = ...,
        env: _OptStr = ...,
    ) -> Mapping[Text, Any]: ...
    async def finish_experiment(
        self, status: Text = ..., env: _OptStr = ...
    ) -> Mapping[Text, Any]: ...
    async def set_tags(
        self,
        tags: _TagMap,
        env: _OptStr = ...,
        append: bool = ...,
    ) -> _TagMap: ...
    async def get_tags(self, env: _OptStr = ...) -> _TagMap: ...
    async def search_experiments(
        self,
        query: _OptStr = ...,
        limit: Optional[int] = ...,
        offset: int = ...,
        sort_by: _OptStr = ...,
        descending: bool = ...,
    ) -> _ExperimentQueryReply: ...
    async def compare_experiments(self, env_ids: _EnvIds) -> _ExperimentQueryReply: ...
    async def suggest_experiment(
        self, params: _OptOps = ..., env: _OptStr = ...
    ) -> _ExperimentQueryReply: ...
    async def hparams(
        self,
        query: _OptStr = ...,
        env_ids: Optional[_EnvIds] = ...,
        mode: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def update_hparams(
        self,
        win: Text,
        query: _OptStr = ...,
        env_ids: Optional[_EnvIds] = ...,
        mode: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def get_window_data(
        self, win: _OptStr = ..., env: _OptStr = ...
    ) -> _SendReturn: ...
    async def set_window_data(
        self, data: Any, win: _OptStr = ..., env: _OptStr = ...
    ) -> _SendReturn: ...
    async def delete_env(self, env: Text) -> _SendReturn: ...
    async def delete_envs(self, env_list: _EnvIds) -> _SendReturn: ...
    async def fork_env(self, prev_eid: Text, eid: Text) -> _SendReturn: ...
    async def get_env_list(self) -> List[Text]: ...
    async def get_env_state(self, env: Text) -> Optional[Mapping[Text, Any]]: ...
    async def win_exists(self, win: Text, env: _OptStr = ...) -> Optional[bool]: ...
    async def check_connection(
        self, timeout_seconds: Union[int, float] = ...
    ) -> bool: ...
    async def replay_log(self, log_filename: Text) -> None: ...
    async def text(
        self,
        text: Text,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        append: bool = ...,
    ) -> _SendReturn: ...
    async def svg(
        self,
        svgstr: _OptStr = ...,
        svgfile: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def matplot(
        self, plot: Any, opts: _OptOps = ..., env: _OptStr = ..., win: _OptStr = ...
    ) -> _SendReturn: ...
    async def save_plotly_figure(
        self, figure: Any, filepath: Text, **kwargs: Any
    ) -> None: ...
    async def plotlyplot(
        self,
        figure: Any,
        win: _OptStr = ...,
        env: _OptStr = ...,
        save_path: _OptStr = ...,
        save_kwargs: Optional[Mapping[Text, Any]] = ...,
    ) -> _SendReturn: ...
    async def image(
        self, img: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    async def image_select(
        self, win: Text, selected: int, env: _OptStr = ...
    ) -> _SendReturn: ...
    async def image_heatmap(
        self,
        img: Tensor,
        heatmap: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def update_image_slider(
        self, win: Text, index: Union[int, float], env: _OptStr = ...
    ) -> _SendReturn: ...
    async def images(
        self,
        tensor: Tensor,
        nrow: int = ...,
        padding: int = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def audio(
        self,
        tensor: Tensor,
        audiofile: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def video(
        self,
        tensor: Tensor = ...,
        dim: Text = ...,
        videofile: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def update_window_opts(
        self, win: Text, opts: Mapping[Text, Any], env: _OptStr = ...
    ) -> _SendReturn: ...
    async def learning_curve(
        self,
        metrics: Mapping[Text, Any],
        step: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        update: _OptStr = ...,
    ) -> _SendReturn: ...
    async def scatter(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
    ) -> _SendReturn: ...
    async def line(
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
    async def heatmap(
        self,
        X: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        update: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def bar(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def histogram(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    async def histogram2d(
        self,
        X: Tensor,
        Y: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def boxplot(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    async def roc_curve(
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
    async def pr_curve(
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
    async def confusion_matrix(
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
    async def surf(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    async def contour(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    async def quiver(
        self,
        X: Tensor,
        Y: Tensor,
        gridX: Optional[Tensor] = ...,
        gridY: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def stem(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def pie(
        self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...
    ) -> _SendReturn: ...
    async def mesh(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def sankey(
        self,
        source: Tensor,
        target: Tensor,
        value: Tensor,
        labels: Optional[List] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def graph(
        self,
        edges: List,
        edgeLabels: Optional[List] = ...,
        nodeLabels: Optional[List] = ...,
        opts: _OptOps = ...,
        env: _OptStr = ...,
        win: _OptStr = ...,
    ) -> _SendReturn: ...
    async def parallel_coordinates(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def violin(
        self,
        X: Tensor,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def properties(
        self,
        data: List,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def html_table(
        self,
        data: List[Any],
        headers: Optional[List[Any]] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def embeddings(
        self,
        features: Tensor,
        labels: Tensor,
        data_getter: Optional[Callable[[int], Any]] = ...,
        data_type: _OptStr = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def sunburst(
        self,
        labels: Tensor,
        parents: Tensor,
        values: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    async def dual_axis_lines(
        self,
        X: Optional[Tensor] = ...,
        Y1: Optional[Tensor] = ...,
        Y2: Optional[Tensor] = ...,
        opts: _OptOps = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
    ) -> _SendReturn: ...
    async def table(
        self,
        data: List[Any],
        headers: Optional[List[Any]] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
