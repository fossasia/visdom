/**
 * Copyright 2017-present, The Visdom Authors
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const allScreenshots = [
  'text_basic',
  'text_update',
  'image_basic',
  'image_save_jpeg',
  'image_history',
  'image_grid',
  'plot_line_basic',
  'plot_line_multiple',
  // 'plot_line_webgl', // disabled due to webgl
  // 'plot_line_update_webgl', // disabled due to webgl
  'plot_line_update',
  'plot_line_many_updates',
  'plot_line_opts',
  'plot_line_opts_update',
  'plot_line_stackedarea',
  'plot_line_maxsize',
  'plot_line_doubleyaxis',
  'plot_line_pytorch',
  'plot_line_stem',
  'plot_scatter_basic',
  'plot_scatter_update_opts',
  'plot_scatter_append',
  // 'plot_scatter_3d', // disabled due to webgl
  'plot_scatter_custom_marker',
  'plot_scatter_custom_colors',
  'plot_scatter_add_trace',
  'plot_scatter_text_labels_1d',
  'plot_scatter_text_labels_2d',
  'plot_bar_basic',
  'plot_bar_stacked',
  'plot_bar_nonstacked',
  'plot_bar_histogram',
  'plot_bar_piechart',
  'plot_surface_basic',
  'plot_surface_basic_withnames',
  'plot_surface_append',
  'plot_surface_append_withnames',
  'plot_surface_remove',
  'plot_surface_remove_withnames',
  'plot_surface_replace',
  'plot_surface_replace_withnames',
  'plot_surface_contour',
  // 'plot_surface_3d', // disabled due to webgl
  'plot_special_boxplot',
  'plot_special_quiver',
  'plot_violin_basic',
  // 'plot_special_mesh', // disabled due to webgl
  // 'plot_special_graph' // disabled as representation is undeterministic
  'misc_plot_matplot',
  'misc_plot_latex',
  'misc_plot_latex_update',
  'misc_video_tensor',
  // 'misc_video_download', // disabled to circumvent problems due to varying download speeds
  'misc_audio_basic',
  // 'misc_audio_download', // disabled to circumvent problems due to varying download speeds
  'misc_arbitrary_visdom',
  'misc_getset_state',
  'properties_basic',
];

const allCompareviews = [
  'plot_line_basic',
  'plot_line_multiple',
  // // 'plot_line_webgl', // disabled due to webgl
  // // 'plot_line_update_webgl', // disabled due to webgl
  'plot_line_update',
  'plot_line_many_updates',
  'plot_line_opts',
  'plot_line_opts_update',
  'plot_line_stackedarea',
  'plot_line_doubleyaxis',
  'plot_line_stem',
  'plot_scatter_basic',
  'plot_scatter_update_opts',
  'plot_scatter_append',
  // 'plot_scatter_3d', // disabled due to webgl
  'plot_scatter_custom_marker',
  'plot_scatter_custom_colors',
  'plot_scatter_add_trace',
  'plot_scatter_text_labels_1d',
  'plot_scatter_text_labels_2d',
  // 'plot_bar_basic', // does not work or not implemented
  'plot_bar_stacked',
  'plot_bar_nonstacked',
  // 'plot_bar_histogram', // does not work or not implemented
  // 'plot_bar_piechart', // does not work or not implemented
  'plot_special_boxplot',
  'plot_violin_basic',
  'misc_plot_latex',
  'misc_plot_latex_update',
];

const screenshotOptions = {
  misc_video_tensor: { threshold: 0.1, maxDiffPixels: 5000 },
  misc_video_download: { threshold: 0.1, maxDiffPixels: 5000 },
  misc_audio_basic: { maxDiffPixels: 5000 },
  misc_plot_latex: { maxDiffPixels: 3000 },
  text_basic: { threshold: 0.05 },
  text_update: { threshold: 0.05 },
};

const compareScreenshotOptions = {
  plot_line_doubleyaxis: { maxDiffPixels: 2000 },
  plot_scatter_append: { maxDiffPixels: 200 },
  plot_scatter_custom_marker: { maxDiffPixels: 200 },
  plot_scatter_add_trace: { maxDiffPixels: 200 },
  plot_line_basic: { maxDiffPixels: 200 },
  plot_line_many_updates: { maxDiffPixels: 200 },
  plot_line_update: { maxDiffPixels: 150 },
  plot_line_opts: { maxDiffPixels: 100 },
  plot_line_opts_update: { maxDiffPixels: 100 },
  plot_line_multiple: { maxDiffPixels: 50 },
  plot_line_stackedarea: { maxDiffPixels: 50 },
  plot_scatter_custom_colors: { maxDiffPixels: 50 },
  plot_scatter_text_labels_1d: { maxDiffPixels: 50 },
  plot_scatter_text_labels_2d: { maxDiffPixels: 50 },
  plot_bar_stacked: { maxDiffPixels: 200 },
  plot_bar_nonstacked: { maxDiffPixels: 200 },
  plot_special_boxplot: { maxDiffPixels: 200 },
  misc_plot_latex: { maxDiffPixels: 3000 },
  misc_plot_latex_update: { maxDiffPixels: 200 },
};

module.exports = {
  allScreenshots,
  allCompareviews,
  screenshotOptions,
  compareScreenshotOptions,
};
