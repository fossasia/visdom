#!/usr/bin/env python3

# Copyright 2017-present, The Visdom Authors
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

import json

class LaTeXExporter:
    def __init__(self):
        pass

    def to_tikz(self, plot_data):
        """Converts Plotly plot data to a TikZ/Pgfplots snippet."""
        # This is a simplified version. A full implementation would be much more complex.
        tikz = [
            r"\begin{tikzpicture}",
            r"\begin{axis}[",
            f"  title={{{plot_data.get('title', 'Exported Plot')}}},",
            r"  xlabel={x},",
            r"  ylabel={y},",
            r"  grid=major,",
            r"]"
        ]

        for trace in plot_data.get('content', {}).get('data', []):
            if trace.get('type') == 'scatter':
                x_vals = trace.get('x', [])
                y_vals = trace.get('y', [])
                name = trace.get('name', 'trace')
                
                tikz.append(f"  \\addplot+ [] coordinates {{")
                for x, y in zip(x_vals, y_vals):
                    tikz.append(f"    ({x}, {y})")
                tikz.append(f"  }};")
                tikz.append(f"  \\addlegendentry{{{name}}}")

        tikz.append(r"\end{axis}")
        tikz.append(r"\end{tikzpicture}")
        
        return "\n".join(tikz)

    def to_latex_table(self, properties_data):
        """Converts properties data to a LaTeX table."""
        latex = [
            r"\begin{table}[h]",
            r"\centering",
            r"\begin{tabular}{|l|l|}",
            r"\hline",
            r"Property & Value \\ \hline"
        ]
        
        # properties_data is typically a list of dicts for Visdom properties pane
        for item in properties_data:
            name = item.get('name', '')
            value = item.get('value', '')
            latex.append(f"{name} & {value} \\\\ \\hline")

        latex.append(r"\end{tabular}")
        latex.append(r"\caption{Experiment Properties}")
        latex.append(r"\end{table}")
        
        return "\n".join(latex)
