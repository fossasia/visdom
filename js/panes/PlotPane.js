/**
 * Copyright 2017-present, The Visdom Authors
 */

import React, { useEffect, useRef, useState } from 'react';

const { usePrevious } = require('../util');
import Pane from './Pane';
const { sgg } = require('ml-savitzky-golay-generalized');

var PlotPane = (props) => {

  const { contentID, content } = props;

  const plotlyRef = useRef();
  const previousContent = usePrevious(content);

  const maxsmoothvalue = 100;

  const [smoothWidgetActive, setSmoothWidgetActive] = useState(false);
  const [smoothvalue, setSmoothValue] = useState(1);


  // -------------------------
  // DOWNLOAD HANDLER (SVG)
  // -------------------------

  const handleDownload = () => {

    if (!plotlyRef.current || !window.Plotly) {

      console.warn("Plot export unavailable: Plotly not ready yet.");

      return;

    }

    try {

      window.Plotly.downloadImage(

        plotlyRef.current,

        {
          format: "svg",
          filename: `${contentID}_plot`,
          width: 1200,
          height: 800,
          scale: 2
        }

      );

    } catch (error) {
      console.warn("Plot export failed:", error);
    }
  };

  const toggleSmoothWidget = () => {
    setSmoothWidgetActive(!smoothWidgetActive);
  };

  const updateSmoothSlider = (val) => {
    setSmoothValue(Number(val));
  };

  useEffect(() => {
    if (window.Plotly && plotlyRef.current) {
      newPlot();
    }
  }, [content, smoothWidgetActive, smoothvalue, props.version]);

  const newPlot = () => {

        let data = content.data;
        let smooth_data = [];

        if (smoothWidgetActive) {

          smooth_data = data

            .filter(d => d.type === 'scatter' && d.mode === 'lines')

            .map(d => {

              let smooth_d = JSON.parse(JSON.stringify(d));

              let windowSize = 2 * smoothvalue + 1;

              smooth_d.showlegend = false;

              if (windowSize < 5 || smooth_d.x.length <= 5) {

                d.opacity = 1;
                return smooth_d;

              }

              windowSize = Math.max(windowSize, 5);

              smooth_d.y = sgg(

                smooth_d.y,

                smooth_d.x,

                { windowSize }

              );

              d.opacity = 0.35;
              smooth_d.opacity = 1;

              return smooth_d;

            });

        }

        content.layout.datarevision = props.version;


        window.Plotly.react(

          contentID,

          data.concat(smooth_data),

          content.layout

        );

      };


      // -------------------------
      // smoothing UI
      // -------------------------

      let contains_line_plots = content.data.some(

        d => d.type === 'scatter' && d.mode === 'lines'

      );


      let smooth_widget_button = '';
      let smooth_widget = '';


      if (contains_line_plots) {

        smooth_widget_button = (

          <button

            key="smooth_widget_button"

            title="smooth lines"

            onClick={toggleSmoothWidget}

            className={

              smoothWidgetActive

                ? 'pull-right active'

                : 'pull-right'

            }

          >

            ~

          </button>

        );


        if (smoothWidgetActive) {

          smooth_widget = (

            <div className="widget">

              <input

                type="range"

                min="1"

                max={maxsmoothvalue}

                value={smoothvalue}

                onInput={

                  ev => updateSmoothSlider(ev.target.value)

                }

              />

            </div>

          );

        }

      }


      // -------------------------
      // render
      // -------------------------

      return (

        <Pane

          {...props}

          handleDownload={handleDownload}

          barwidgets={[

            smooth_widget_button

          ]}

          widgets={[

            smooth_widget

          ]}

          enablePropertyList

        >

          <div

            id={contentID}

            style={{

              height: '100%',
              width: '100%'

            }}

            className="plotly-graph-div"

            ref={plotlyRef}

          />

        </Pane>

      );

    };


    PlotPane = React.memo(

      PlotPane,

      (props, nextProps) => {

        if (props.contentID !== nextProps.contentID) return false;

        if (props.h !== nextProps.h || props.w !== nextProps.w) return false;

        if (props.isFocused !== nextProps.isFocused) return false;

        return true;

      }

    );

    export default PlotPane;