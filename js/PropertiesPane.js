/**
 * Copyright 2017-present, Facebook, Inc.
 * All rights reserved.
 *
 * This source code is licensed under the license found in the
 * LICENSE file in the root directory of this source tree.
 *
 */

const Pane = require('./Pane');


class Text extends React.Component {
    constructor(props) {
        super(props);
        this.state = {value: props.value};
    }

    handleChange = (event) => {
        let newValue = event.target.value;
        if( this.props.validateHandler && !this.props.validateHandler(newValue)) {
            event.preventDefault();
        } else {
            this.setState({value: newValue});
        }
    };

    handleKeyPress = (event) => {
        if( event.key === "Enter") {
            if( this.props.submitHandler ) {
                this.props.submitHandler(this.state.value);
            }
        }
    };

    componentWillReceiveProps(nextProps) {
        if( this.state.value !== nextProps.value) {
            this.setState({value: nextProps.value});
        }
    }

    render() {
        return (
            <input type="text" value={this.state.value} onChange={this.handleChange} onKeyPress={this.handleKeyPress}/>
        );
    }
}

class PropertiesPane extends React.Component {

  handleDownload = () => {
    var blob = new Blob([JSON.stringify(this.props.content)], {type:"application/json"});
    var url = window.URL.createObjectURL(blob);
    var link = document.createElement("a");
    link.download = 'visdom_properties.json';
    link.href = url;
    link.click();
  };

  updateValue = (propId, value) => {
      this.props.onFocus(this.props.id, () => {
          this.props.appApi.sendPaneMessage(
              {
                  event_type: 'PropertyUpdate',
                  propertyId: propId,
                  value: value
              }
          );
      });
  };

  renderPropertyValue = (prop, propId) => {
      switch(prop.type) {
          case 'text':
              return <Text
                  value={prop.value}
                  submitHandler={(value) => this.updateValue(propId, value)}
              />;
          case 'number':
              return <Text
                  value={prop.value}
                  submitHandler={(value) => this.updateValue(propId, value)}
                  validateHandler={(value) => value.match(/^[0-9]*([.][0-9]*)?$/i)}
              />;
          case 'button':
              return <button
                  className="btn btn-sm"
                  onClick={() => this.updateValue(propId, "clicked")}
              >{prop.value}</button>
      }
  };

  render() {
     return (
      <Pane {...this.props} handleDownload={this.handleDownload}>
        <div className="content-properties">
            <table className="table table-bordered table-condensed table-properties">
            {this.props.content.map((prop, propId) =>
                <tr key={propId}>
                    <td className="table-properties-name">{prop.name}</td>
                    <td className="table-properties-value">{this.renderPropertyValue(prop, propId)}</td>
                </tr>
            )}
            </table>
        </div>
      </Pane>
    )
  }
}

module.exports = PropertiesPane;
