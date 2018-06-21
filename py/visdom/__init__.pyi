from typing import Optional, List, Any, Union, Mapping, overload, AnyStr, Text

### Type aliases for commonly-used types.
# For optional 'options' parameters.
# The options parameters can be strongly-typed with the proposed TypedDict type once that is incorporated into the standard.
# See  http://mypy.readthedocs.io/en/latest/more_types.html#typeddict.
_OptOps = Optional[Mapping[AnyStr, Any]]
_OptStr = Optional[AnyStr]  # For optional string parameters, like 'window' and 'env'.

# No widely-deployed stubs exist at the moment for torch or numpy. When they are available, the correct type of the tensor-like inputs
# to the plotting commands should be
# Tensor = Union[torch.Tensor, numpy.ndarray]
# For now, we fall back to 'Any'.
Tensor = Any

# The return type of 'Visdom._send', which is turn is also the return type of most of the the plotting commands.
# It technically can return a union of several different types, but in normal usage,
# it will return a single string. We only type it as such to prevent the need for users to unwrap the union.
# See https://github.com/python/mypy/issues/1693.
_SendReturn = Text

class Visdom:
    def __init__(
        self,
        server: AnyStr = ...,
        endpoint: AnyStr = ...,
        port: int = ...,
        ipv6: bool = ...,
        http_proxy_host: _OptStr = ...,
        http_proxy_port: Optional[int] = ...,
        env: AnyStr = ...,
        send: bool = ...,
        raise_exceptions: Optional[bool] = ...,
        use_incoming_socket: bool = ...,
        log_to_filename: _OptStr = ...,
    ) -> None: ...
    def _send(self, msg, endpoint: AnyStr = ..., quiet: bool = ..., from_log: bool = ...) -> _SendReturn: ...
    def save(self, envs: List[AnyStr]) -> _SendReturn: ...
    def close(self, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
    def get_window_data(self, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
    def delete_env(self, env: AnyStr) -> _SendReturn: ...
    def win_exists(self, win: AnyStr, env: _OptStr = ...) -> Optional[bool]: ...
    def check_connection(self) -> bool: ...
    def replay_log(self, log_filename: AnyStr) -> None: ...
    def text(self,
        text: AnyStr,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
        append: bool = ...,
    ) -> _SendReturn: ...
    @overload
    def svg(self, svgstr: _OptStr = ..., win: _OptStr = ..., env: _OptStr = ..., ops: _OptOps = ...) -> _SendReturn: ...
    @overload
    def svg(self, svgfile: _OptStr = ..., win: _OptStr = ..., env: _OptStr = ..., ops: _OptOps = ...) -> _SendReturn: ...
    def matplot(self, plot: Any, opts: _OptOps = ..., env: _OptStr = ..., win: _OptStr = ...) -> _SendReturn: ...
    def image(self, img: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
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
    def video(self,
        tensor: Tensor=...,
        videofile: _OptStr=...,
        win:_OptStr=...,
        env:_OptStr=...,
        opts:_OptOps=...
    ) -> _SendReturn: ...
    def update_window_opts(self, win: AnyStr, opts: Mapping[AnyStr, Any], env: _OptStr = ...) -> _SendReturn: ...
    def scatter(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
    ) -> _SendReturn: ...
    def line(
        self,
        Y: Tensor,
        X: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
    ) -> _SendReturn: ...
    def grid(
        self,
        X: Tensor,
        Y: Tensor,
        gridX: Optional[Tensor] = ...,
        gridY: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...,
    ) -> _SendReturn: ...
    def heatmap(self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def bar(self, X: Tensor, Y: Optional[Tensor] = ..., win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def histogram(self, X: Tensor, win: _OptStr= ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def boxplot(self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def surf(self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def contour(self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def quiver(
        self,
        X: Tensor,
        Y: Tensor,
        gridX: Optional[Tensor] = ...,
        gridY: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        opts: _OptOps = ...
    ) -> _SendReturn: ...
    def stem(self, X: Tensor, Y: Optional[Tensor] = ..., win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def pie(self, X: Tensor, win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
    def mesh(self, X: Tensor, Y: Optional[Tensor] = ..., win: _OptStr = ..., env: _OptStr = ..., opts: _OptOps = ...) -> _SendReturn: ...
