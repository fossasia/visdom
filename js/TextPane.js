import EventSystem from "./EventSystem";

/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const Pane = require('./Pane');

class TextPane extends React.Component {

  onEvent = (e) => {
      if( !this.props.isFocused ) {
          return;
      }

      switch(e.type) {
          case 'keydown':
          case 'keypress':
              e.preventDefault();
              break;
          case 'keyup':
              this.props.appApi.sendPaneMessage(
                  {
                      event_type: 'KeyPress',
                      key: event.key,
                      key_code: event.keyCode,
                  }
              );
              break;
      }
  };

  componentDidMount() {
      EventSystem.subscribe('global.event', this.onEvent)
  }
  componentWillMount() {
      EventSystem.unsubscribe('global.event', this.onEvent)
  }

  handleDownload = () => {
    var blob = new Blob([this.props.content], {type:"text/plain"});
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.download = 'visdom_text.txt';
    link.href = url;
    link.click();
  }

  render() {
    return (
      <Pane {...this.props} handleDownload={this.handleDownload}>
        <div className="content-text"><div
          dangerouslySetInnerHTML={{__html: this.props.content}}>
        </div></div>
      </Pane>
    )
  }
}

module.exports = TextPane;
