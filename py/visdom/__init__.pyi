# Copyright 2017-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

from typing import Optional, List, Any, Union, Mapping, overload, Text

### Type aliases for commonly-used types.
# For optional 'options' parameters.
# The options parameters can be strongly-typed with the proposed TypedDict type once that is incorporated into the standard.
# See  http://mypy.readthedocs.io/en/latest/more_types.html#typeddict.
_OptOps = Optional[Mapping[Text, Any]]
_OptStr = Optional[Text]  # For optional string parameters, like 'window' and 'env'.

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

class Visdom:
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
        send: bool = ...,
        raise_exceptions: Optional[bool] = ...,
        use_incoming_socket: bool = ...,
        log_to_filename: _OptStr = ...,
    ) -> None: ...
    def _send(self, msg, endpoint: Text = ..., quiet: bool = ..., from_log: bool = ...) -> _SendReturn: ...
    def save(self, envs: List[Text]) -> _SendReturn: ...
    def close(self, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
    def get_window_data(self, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
    def delete_env(self, env: Text) -> _SendReturn: ...
    def win_exists(self, win: Text, env: _OptStr = ...) -> Optional[bool]: ...
    def check_connection(self) -> bool: ...
    def replay_log(self, log_filename: Text) -> None: ...
    def text(self,
        text: Text,
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
    def plotlyplot(self, figure: Any, win: _OptStr = ..., env: _OptStr = ...) -> _SendReturn: ...
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
    def update_window_opts(self, win: Text, opts: Mapping[Text, Any], env: _OptStr = ...) -> _SendReturn: ...
    def scatter(
        self,
        X: Tensor,
        Y: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
        opts: _OptOpts = ...
    ) -> _SendReturn: ...
    def line(
        self,
        Y: Tensor,
        X: Optional[Tensor] = ...,
        win: _OptStr = ...,
        env: _OptStr = ...,
        update: _OptStr = ...,
        name: _OptStr = ...,
        opts: _OptOps = ...
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
