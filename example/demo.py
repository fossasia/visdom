#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import numpy as np
import time
from visdom import Visdom
import argparse
from components.text import text_basic, text_update, text_callbacks, text_close, text_fork_part1, text_fork_part2
from components.image import image_basic, image_callback, image_callback2, image_save_jpeg, image_history, image_grid, image_svg
from components.plot_scatter import plot_scatter_basic, plot_scatter_update_opts, plot_scatter_append, plot_scatter_3d, plot_scatter_custom_marker, plot_scatter_custom_colors, plot_scatter_add_trace, plot_scatter_text_labels_1d, plot_scatter_text_labels_2d
from components.plot_bar import plot_bar_basic, plot_bar_stacked, plot_bar_nonstacked, plot_bar_histogram, plot_bar_piechart
from components.plot_surface import plot_surface_basic, plot_surface_basic_withnames, plot_surface_append, plot_surface_append_withnames, plot_surface_remove, plot_surface_remove_withnames, plot_surface_replace, plot_surface_replace_withnames, plot_surface_contour, plot_surface_3d
from components.plot_line import plot_line_basic, plot_line_multiple, plot_line_webgl, plot_line_update_webgl, plot_line_update, plot_line_opts, plot_line_opts_update, plot_line_stackedarea, plot_line_maxsize, plot_line_doubleyaxis, plot_line_pytorch, plot_line_stem
from components.plot_special import plot_special_boxplot, plot_special_quiver, plot_special_mesh, plot_special_graph
from components.properties import properties_basic, properties_callbacks
from components.misc import misc_plot_matplot, misc_plot_latex, misc_plot_latex_update, misc_video_tensor, misc_video_download, misc_audio_basic, misc_audio_download, misc_arbitrary_visdom, misc_getset_state


# This demo shows all features in a single environment.
def run_demo(viz, env, args):
    global input
    assert viz.check_connection(timeout_seconds=3), \
        'No connection could be formed quickly'

    # ============ #
    # text windows #
    # ============ #
    text_basic(viz, env, args)
    text_update(viz, env, args)
    text_callbacks(viz, env, args)
    text_close(viz, env, args)

    # ===== #
    # image #
    # ===== #
    image_basic(viz, env, args)
    image_callback(viz, env, args)
    image_save_jpeg(viz, env, args)
    image_history(viz, env, args)
    image_grid(viz, env, args)

    # ========== #
    # line plots #
    # ========== #
    plot_line_basic(viz, env, args)
    plot_line_multiple(viz, env, args)
    plot_line_webgl(viz, env, args)
    plot_line_update_webgl(viz, env, args)
    plot_line_update(viz, env, args)
    plot_line_opts(viz, env, args)
    plot_line_opts_update(viz, env, args)
    plot_line_stackedarea(viz, env, args)
    plot_line_maxsize(viz, env, args)
    plot_line_doubleyaxis(viz, env, args)
    plot_line_pytorch(viz, env, args)
    plot_line_stem(viz, env, args)

    # ============= #
    # scatter plots #
    # ============= #
    plot_scatter_basic(viz, env, args)
    plot_scatter_update_opts(viz, env, args)
    plot_scatter_append(viz, env, args)
    plot_scatter_3d(viz, env, args)
    plot_scatter_custom_marker(viz, env, args)
    plot_scatter_custom_colors(viz, env, args)
    plot_scatter_add_trace(viz, env, args)
    plot_scatter_text_labels_1d(viz, env, args)
    plot_scatter_text_labels_2d(viz, env, args)

    # ========= #
    # bar plots #
    # ========= #
    plot_bar_basic(viz, env, args)
    plot_bar_stacked(viz, env, args)
    plot_bar_nonstacked(viz, env, args)
    plot_bar_histogram(viz, env, args)
    plot_bar_piechart(viz, env, args)

    # ============= #
    # heatmap plots #
    # ============= #
    plot_surface_basic(viz, env, args)
    plot_surface_basic_withnames(viz, env, args)
    plot_surface_append(viz, env, args)
    plot_surface_append_withnames(viz, env, args)
    plot_surface_remove(viz, env, args)
    plot_surface_remove_withnames(viz, env, args)
    plot_surface_replace(viz, env, args)
    plot_surface_replace_withnames(viz, env, args)
    plot_surface_contour(viz, env, args)
    plot_surface_3d(viz, env, args)

    # ============= #
    # special plots #
    # ============= #
    plot_special_boxplot(viz, env, args)
    plot_special_quiver(viz, env, args)
    plot_special_mesh(viz, env, args)
    plot_special_graph(viz, env, args)

    # ==== #
    # misc #
    # ==== #
    misc_plot_matplot(viz, env, args)
    misc_plot_latex(viz, env, args)
    misc_plot_latex_update(viz, env, args)
    misc_video_tensor(viz, env, args)
    misc_video_download(viz, env, args)
    misc_audio_basic(viz, env, args)
    misc_audio_download(viz, env, args)
    misc_arbitrary_visdom(viz, env, args)
    misc_getset_state(viz, env, args)
       
if __name__ == '__main__':
    demos_list = [fn for fn in locals().keys() if fn.split("_")[0] in ["text", "image", "plot", "misc"]]
 
    DEFAULT_PORT = 8097
    DEFAULT_HOSTNAME = "http://localhost"
    parser = argparse.ArgumentParser(description='Demo arguments')
    parser.add_argument('-port', metavar='port', type=int, default=DEFAULT_PORT,
                        help='port the visdom server is running on.')
    parser.add_argument('-server', metavar='server', type=str,
                        default=DEFAULT_HOSTNAME,
                        help='Server address of the target to run the demo on.')
    parser.add_argument('-base_url', metavar='base_url', type=str,
                    default='/',
                    help='Base Url.')
    parser.add_argument('-username', metavar='username', type=str,
                    default='',
                    help='username.')
    parser.add_argument('-password', metavar='password', type=str,
                    default='',
                    help='password.')
    parser.add_argument('-use_incoming_socket', metavar='use_incoming_socket', type=bool,
                    default=True,
                    help='use_incoming_socket.')
    parser.add_argument('-run', help='demo-function to run. (default: \'all\'). possible values:'+(", ".join(demos_list)), type=str, default="all")
    parser.add_argument('-env', help='env name to save demo in. By default, main is used for \'-run all\' and otherwise the demo chosen using \'-run\'.', default="")
    # parser.add_argument('-env', help='The env to save the demo to.', default="main")
    parser.add_argument('-env_suffix', help='The env suffix to save the demo to.', default="")
    parser.add_argument('-args', nargs='*', help='Additonal arguments passed to the requested demo. (Mainly to be used for automated testing).', default="")
    parser.add_argument('-seed', help='Seed to use for random data in -testing mode. (Default: 42)', default=42)
    parser.add_argument('-testing', help='(To be mainly to be used for automated testing). If set to true, waits 10 seconds for callback actions and closes then automatically. Also this sets a random seed for consistent outcomes.', default=False, action='store_true')
    FLAGS = parser.parse_args()

    viz = Visdom(port=FLAGS.port, server=FLAGS.server, base_url=FLAGS.base_url, username=FLAGS.username, password=FLAGS.password, \
            use_incoming_socket=FLAGS.use_incoming_socket)

    if FLAGS.testing:
        np.random.seed(int(FLAGS.seed))

    if FLAGS.run == "all":
        try:
            run_demo(viz, FLAGS.env if FLAGS.env else None, FLAGS.args)
        except Exception as e:
            print(
                "The visdom experienced an exception while running: {}\n"
                "The demo displays up-to-date functionality with the GitHub "
                "version, which may not yet be pushed to pip. Please upgrade "
                "using `pip install -e .` or `easy_install .`\n"
                "If this does not resolve the problem, please open an issue on "
                "our GitHub.".format(repr(e))
            )
    else:
        locals()[FLAGS.run](viz, FLAGS.run + FLAGS.env_suffix if not FLAGS.env else FLAGS.env, FLAGS.args)

    if len(viz.event_handlers) > 0:
        if FLAGS.testing:
            time.sleep(10)
        else:
            try:
                input = raw_input  # for Python 2 compatibility
            except NameError:
                pass
            input('Waiting for callbacks, press enter to quit.')
