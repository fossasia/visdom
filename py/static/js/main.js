!function(e){function t(a){if(n[a])return n[a].exports;var o=n[a]={exports:{},id:a,loaded:!1};return e[a].call(o.exports,o,o.exports,t),o.loaded=!0,o.exports}var n={};return t.m=e,t.c=n,t.p="",t(0)}([function(e,t,n){e.exports=n(6)},function(e,t){"use strict";function n(e,t){if(!(e instanceof t))throw new TypeError("Cannot call a class as a function")}function a(e,t){if(!e)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return!t||"object"!=typeof t&&"function"!=typeof t?e:t}function o(e,t){if("function"!=typeof t&&null!==t)throw new TypeError("Super expression must either be null or a function, not "+typeof t);e.prototype=Object.create(t&&t.prototype,{constructor:{value:e,enumerable:!1,writable:!0,configurable:!0}}),t&&(Object.setPrototypeOf?Object.setPrototypeOf(e,t):e.__proto__=t)}var r=function(){function e(e,t){for(var n=0;n<t.length;n++){var a=t[n];a.enumerable=a.enumerable||!1,a.configurable=!0,"value"in a&&(a.writable=!0),Object.defineProperty(e,a.key,a)}}return function(t,n,a){return n&&e(t.prototype,n),a&&e(t,a),t}}(),s=function(e){function t(){var e,o,r,s;n(this,t);for(var i=arguments.length,l=Array(i),c=0;c<i;c++)l[c]=arguments[c];return o=r=a(this,(e=t.__proto__||Object.getPrototypeOf(t)).call.apply(e,[this].concat(l))),r.close=function(){r.props.onClose(r.props.id)},r.focus=function(){r.props.onFocus(r.props.id)},r.download=function(){r.props.handleDownload&&r.props.handleDownload()},r.resize=function(){r.props.resize&&r.props.onResize()},r.getWindowSize=function(){return{h:r._windowRef.clientHeight,w:r._windowRef.clientWidth}},r.getContentSize=function(){return{h:r._windowRef.clientHeight-r._barRef.scrollHeight,w:r._windowRef.clientWidth}},s=o,a(r,s)}return o(t,e),r(t,[{key:"shouldComponentUpdate",value:function(e,t){return this.props.contentID!==e.contentID||(this.props.h!==e.h||this.props.w!==e.w||this.props.children!==e.children)}},{key:"render",value:function(){var e=this,t=classNames({window:!0}),n=classNames({bar:!0,focus:this.props.isFocused});return React.createElement("div",{className:t,ref:function(t){return e._windowRef=t}},React.createElement("div",{className:n,onClick:this.focus,ref:function(t){return e._barRef=t}},React.createElement("button",{title:"close",onClick:this.close},"X"),React.createElement("button",{title:"save",onClick:this.download},"⤓"),React.createElement("div",null,this.props.title)),React.createElement("div",{className:"content"},this.props.children))}}]),t}(React.Component);e.exports=s},function(e,t,n){"use strict";function a(e,t){if(!(e instanceof t))throw new TypeError("Cannot call a class as a function")}function o(e,t){if(!e)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return!t||"object"!=typeof t&&"function"!=typeof t?e:t}function r(e,t){if("function"!=typeof t&&null!==t)throw new TypeError("Super expression must either be null or a function, not "+typeof t);e.prototype=Object.create(t&&t.prototype,{constructor:{value:e,enumerable:!1,writable:!0,configurable:!0}}),t&&(Object.setPrototypeOf?Object.setPrototypeOf(e,t):e.__proto__=t)}var s=Object.assign||function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var a in n)Object.prototype.hasOwnProperty.call(n,a)&&(e[a]=n[a])}return e},i=function(){function e(e,t){for(var n=0;n<t.length;n++){var a=t[n];a.enumerable=a.enumerable||!1,a.configurable=!0,"value"in a&&(a.writable=!0),Object.defineProperty(e,a.key,a)}}return function(t,n,a){return n&&e(t.prototype,n),a&&e(t,a),t}}(),l=n(1),c=function(e){function t(){var e,n,r,s;a(this,t);for(var i=arguments.length,l=Array(i),c=0;c<i;c++)l[c]=arguments[c];return n=r=o(this,(e=t.__proto__||Object.getPrototypeOf(t)).call.apply(e,[this].concat(l))),r._paneRef=null,r.state={scale:1},r.handleDownload=function(){var e=document.createElement("a");e.download=(r.props.title||"visdom_image")+".jpg",e.href=r.props.content.src,e.click()},r.handleZoom=function(e){var t=e.deltaMode===e.DOM_DELTA_PIXEL?e.deltaY:40*e.deltaY,n=Math.exp(-t/5e3);r.setState({scale:r.state.scale*n}),e.stopPropagation(),e.preventDefault()},r.resetZoom=function(e){r.setState({scale:1})},s=n,o(r,s)}return r(t,e),i(t,[{key:"render",value:function(){var e=this,t=this.props.content;return React.createElement(l,s({},this.props,{handleDownload:this.handleDownload,ref:function(t){return e._paneRef=t}}),React.createElement("img",{className:"content-image",src:t.src,width:Math.ceil(1+this.props.width*this.state.scale)+"px",height:Math.ceil(1+this.props.height*this.state.scale)+"px",onWheel:this.handleZoom.bind(this),onDoubleClick:this.resetZoom.bind(this)}),React.createElement("p",{className:"caption"},t.caption))}}]),t}(React.Component);e.exports=c},function(e,t,n){"use strict";function a(e,t){if(!(e instanceof t))throw new TypeError("Cannot call a class as a function")}function o(e,t){if(!e)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return!t||"object"!=typeof t&&"function"!=typeof t?e:t}function r(e,t){if("function"!=typeof t&&null!==t)throw new TypeError("Super expression must either be null or a function, not "+typeof t);e.prototype=Object.create(t&&t.prototype,{constructor:{value:e,enumerable:!1,writable:!0,configurable:!0}}),t&&(Object.setPrototypeOf?Object.setPrototypeOf(e,t):e.__proto__=t)}var s=Object.assign||function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var a in n)Object.prototype.hasOwnProperty.call(n,a)&&(e[a]=n[a])}return e},i=function(){function e(e,t){for(var n=0;n<t.length;n++){var a=t[n];a.enumerable=a.enumerable||!1,a.configurable=!0,"value"in a&&(a.writable=!0),Object.defineProperty(e,a.key,a)}}return function(t,n,a){return n&&e(t.prototype,n),a&&e(t,a),t}}(),l=n(1),c=function(e){function t(){var e,n,r,s;a(this,t);for(var i=arguments.length,l=Array(i),c=0;c<i;c++)l[c]=arguments[c];return n=r=o(this,(e=t.__proto__||Object.getPrototypeOf(t)).call.apply(e,[this].concat(l))),r._paneRef=null,r._plotlyRef=null,r._width=null,r._height=null,r.newPlot=function(){Plotly.newPlot(r.props.contentID,r.props.content.data,r.props.content.layout,{showLink:!0,linkText:" "})},r.handleDownload=function(){Plotly.downloadImage(r._plotlyRef,{format:"svg",filename:r.props.contentID})},r.resize=function(){r.componentDidUpdate()},s=n,o(r,s)}return r(t,e),i(t,[{key:"componentDidMount",value:function(){this.newPlot()}},{key:"componentDidUpdate",value:function(e,t){this.newPlot()}},{key:"shouldComponentUpdate",value:function(e,t){return this.props.contentID!==e.contentID||(this.props.h!==e.h||this.props.w!==e.w)}},{key:"render",value:function(){var e=this;return React.createElement(l,s({},this.props,{handleDownload:this.handleDownload,ref:function(t){return e._paneRef=t}}),React.createElement("div",{id:this.props.contentID,style:{height:"100%",width:"100%"},className:"plotly-graph-div",ref:function(t){return e._plotlyRef=t}}))}}]),t}(React.Component);e.exports=c},function(e,t,n){"use strict";function a(e,t){if(!(e instanceof t))throw new TypeError("Cannot call a class as a function")}function o(e,t){if(!e)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return!t||"object"!=typeof t&&"function"!=typeof t?e:t}function r(e,t){if("function"!=typeof t&&null!==t)throw new TypeError("Super expression must either be null or a function, not "+typeof t);e.prototype=Object.create(t&&t.prototype,{constructor:{value:e,enumerable:!1,writable:!0,configurable:!0}}),t&&(Object.setPrototypeOf?Object.setPrototypeOf(e,t):e.__proto__=t)}var s=Object.assign||function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var a in n)Object.prototype.hasOwnProperty.call(n,a)&&(e[a]=n[a])}return e},i=function(){function e(e,t){for(var n=0;n<t.length;n++){var a=t[n];a.enumerable=a.enumerable||!1,a.configurable=!0,"value"in a&&(a.writable=!0),Object.defineProperty(e,a.key,a)}}return function(t,n,a){return n&&e(t.prototype,n),a&&e(t,a),t}}(),l=n(1),c=function(e){function t(){var e,n,r,s;a(this,t);for(var i=arguments.length,l=Array(i),c=0;c<i;c++)l[c]=arguments[c];return n=r=o(this,(e=t.__proto__||Object.getPrototypeOf(t)).call.apply(e,[this].concat(l))),r.handleDownload=function(){var e=new Blob([r.props.content],{type:"text/plain"}),t=window.URL.createObjectURL(e),n=document.createElement("a");n.download="visdom_text.txt",n.href=t,n.click()},s=n,o(r,s)}return r(t,e),i(t,[{key:"render",value:function(){return React.createElement(l,s({},this.props,{handleDownload:this.handleDownload}),React.createElement("div",{className:"content-text"},React.createElement("div",{dangerouslySetInnerHTML:{__html:this.props.content}})))}}]),t}(React.Component);e.exports=c},function(e,t){"use strict";function n(e,t){if(!(e instanceof t))throw new TypeError("Cannot call a class as a function")}function a(e,t){if(!e)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return!t||"object"!=typeof t&&"function"!=typeof t?e:t}function o(e,t){if("function"!=typeof t&&null!==t)throw new TypeError("Super expression must either be null or a function, not "+typeof t);e.prototype=Object.create(t&&t.prototype,{constructor:{value:e,enumerable:!1,writable:!0,configurable:!0}}),t&&(Object.setPrototypeOf?Object.setPrototypeOf(e,t):e.__proto__=t)}Object.defineProperty(t,"__esModule",{value:!0});var r=Object.assign||function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var a in n)Object.prototype.hasOwnProperty.call(n,a)&&(e[a]=n[a])}return e},s=function(){function e(e,t){for(var n=0;n<t.length;n++){var a=t[n];a.enumerable=a.enumerable||!1,a.configurable=!0,"value"in a&&(a.writable=!0),Object.defineProperty(e,a.key,a)}}return function(t,n,a){return n&&e(t.prototype,n),a&&e(t,a),t}}(),i=function(e){return function(t){function i(){var e,t,o,r;n(this,i);for(var s=arguments.length,l=Array(s),c=0;c<s;c++)l[c]=arguments[c];return t=o=a(this,(e=i.__proto__||Object.getPrototypeOf(i)).call.apply(e,[this].concat(l))),o.state={width:1280,cols:100},o.mounted=!1,o.resizeTimer=null,o.onWindowResizeStop=function(){if(o.mounted){var e=o.state.width,t=ReactDOM.findDOMNode(o);o.setState({width:t.offsetWidth,cols:t.offsetWidth/e*o.state.cols},function(){o.props.onWidthChange(o.state.width,o.state.cols)})}},o.onWindowResize=function(e){o.resizeTimer&&clearTimeout(o.resizeTimer),o.resizeTimer=setTimeout(o.onWindowResizeStop,200)},r=t,a(o,r)}return o(i,t),s(i,[{key:"componentDidMount",value:function(){this.mounted=!0,window.addEventListener("resize",this.onWindowResize),this.onWindowResize()}},{key:"componentWillUnmount",value:function(){this.mounted=!1,window.removeEventListener("resize",this.onWindowResize)}},{key:"render",value:function(){return this.props.measureBeforeMount&&!this.mounted?React.createElement("div",{className:this.props.className,style:this.props.style}):React.createElement(e,r({},this.props,this.state))}}]),i}(React.Component)};t.default=i},function(e,t,n){"use strict";function a(e,t){if(!(e instanceof t))throw new TypeError("Cannot call a class as a function")}function o(e,t){if(!e)throw new ReferenceError("this hasn't been initialised - super() hasn't been called");return!t||"object"!=typeof t&&"function"!=typeof t?e:t}function r(e,t){if("function"!=typeof t&&null!==t)throw new TypeError("Super expression must either be null or a function, not "+typeof t);e.prototype=Object.create(t&&t.prototype,{constructor:{value:e,enumerable:!1,writable:!0,configurable:!0}}),t&&(Object.setPrototypeOf?Object.setPrototypeOf(e,t):e.__proto__=t)}function s(){ReactDOM.render(React.createElement(R,null),document.getElementById("app")),document.removeEventListener("DOMContentLoaded",s)}var i=Object.assign||function(e){for(var t=1;t<arguments.length;t++){var n=arguments[t];for(var a in n)Object.prototype.hasOwnProperty.call(n,a)&&(e[a]=n[a])}return e},l=function(){function e(e,t){for(var n=0;n<t.length;n++){var a=t[n];a.enumerable=a.enumerable||!1,a.configurable=!0,"value"in a&&(a.writable=!0),Object.defineProperty(e,a.key,a)}}return function(t,n,a){return n&&e(t.prototype,n),a&&e(t,a),t}}(),c=n(4),u=n(2),p=n(3),f=n(5).default,d=f(ReactGridLayout),h=ReactGridLayout.utils.sortLayoutItemsByRowCol,m=ReactGridLayout.utils.getLayoutItem,y=5,v=10,b={image:u,plot:p,text:c},w={image:[20,20],plot:[30,24],text:[20,20]},g={content:{top:"50%",left:"50%",right:"auto",bottom:"auto",marginRight:"-50%",transform:"translate(-50%, -50%)"}},E="current",R=function(e){function t(){var e,n,r,s;a(this,t);for(var i=arguments.length,l=Array(i),c=0;c<i;c++)l[c]=arguments[c];return n=r=o(this,(e=t.__proto__||Object.getPrototypeOf(t)).call.apply(e,[this].concat(l))),r.state={connected:!1,sessionID:null,panes:{},focusedPaneID:null,envID:ACTIVE_ENV,saveText:ACTIVE_ENV,layoutID:E,envList:ENV_LIST.slice(),filter:"",filterField:"",layout:[],cols:100,width:1280,layoutLists:new Map([["main",new Map([[E,new Map]])]]),showEnvModal:!1,showViewModal:!1,modifyID:null},r._bin=null,r._socket=null,r._envFieldRef=null,r._filterFieldRef=null,r._timeoutID=null,r._pendingPanes=[],r.colWidth=function(){return(r.state.width-v*(r.state.cols-1)-2*v)/r.state.cols},r.p2w=function(e){var t=r.colWidth();return(e+v)/(t+v)},r.p2h=function(e){return(e+v)/(y+v)},r.keyLS=function(e){return r.state.envID+"_"+e},r.correctPathname=function(){var e=window.location.pathname;return"/"!=e.slice(-1)&&(e+="/"),e},r.addPaneBatched=function(e){r._timeoutID||(r._timeoutID=setTimeout(r.processBatchedPanes,100)),r._pendingPanes.push(e)},r.processBatchedPanes=function(){var e=Object.assign({},r.state.panes),t=r.state.layout.slice();r._pendingPanes.forEach(function(n){r.processPane(n,e,t)}),r._pendingPanes=[],r._timeoutID=null,r.setState({panes:e,layout:t})},r.processPane=function(e,t,n){var a=e.id in t;if(t[e.id]=e,a){var o=m(n,e.id);e.width&&(o.w=r.p2w(e.width)),e.height&&(o.h=Math.ceil(r.p2h(e.height+14))),e.content.caption&&(o.h+=1)}else{var s=JSON.parse(localStorage.getItem(r.keyLS(e.id)));if(s){var i=s;r._bin.content.push(i)}else{var l=w[e.type][0],c=w[e.type][1];e.width&&(l=r.p2w(e.width)),e.height&&(c=Math.ceil(r.p2h(e.height+14))),e.content.caption&&(c+=1),r._bin.content.push({width:l,height:c});var u=r._bin.position(n.length,r.state.cols),i={i:e.id,w:l,h:c,width:l,height:c,x:u.x,y:u.y,static:!1}}n.push(i)}},r.connect=function(){if(!r._socket){var e=window.location,t=new WebSocket("ws://"+e.host+r.correctPathname()+"socket");t.onmessage=r._handleMessage,t.onopen=function(){r.setState({connected:!0})},t.onerror=t.onclose=function(){r.setState({connected:!1},function(){r._socket=null})},r._socket=t}},r._handleMessage=function(e){var t=JSON.parse(e.data);switch(t.command){case"register":r.setState({sessionID:t.data},function(){r.selectEnv(r.state.envID)});break;case"pane":case"window":r.addPaneBatched(t);break;case"reload":for(var n in t.data)localStorage.setItem(r.keyLS(n),JSON.stringify(t.data[n]));break;case"close":r.closePane(t.data);break;case"layout":r.relayout();break;case"env_update":var a=r.state.layoutLists;for(var o in t.data)a.has(t.data[o])||a.set(t.data[o],new Map([[E,new Map]]));r.setState({envList:t.data,layoutLists:a});break;default:console.error("unrecognized command",t)}},r.disconnect=function(){r._socket.close()},r.closePane=function(e){var t=arguments.length>1&&void 0!==arguments[1]&&arguments[1],n=!(arguments.length>2&&void 0!==arguments[2])||arguments[2],a=Object.assign({},r.state.panes);if(delete a[e],t||(localStorage.removeItem(r.keyLS(r.id)),r.sendSocketMessage({cmd:"close",data:e,eid:r.state.envID})),n){var o=r.state.focusedPaneID,s=r.state.layout.filter(function(t){return t.i!==e});r.setState({layout:s,panes:a,focusedPaneID:o===e?null:o},function(){r.relayout()})}},r.closeAllPanes=function(){Object.keys(r.state.panes).map(function(e){r.closePane(e,!1,!1)}),r.rebin(),r.setState({layout:[],panes:{},focusedPaneID:null})},r.selectEnv=function(e){var t=e===r.state.envID;r.setState({envID:e,saveText:e,panes:t?r.state.panes:{},layout:t?r.state.layout:[],focusedPaneID:t?r.state.focusedPaneID:null}),$.post(r.correctPathname()+"env/"+e,JSON.stringify({sid:r.state.sessionID}))},r.deleteEnv=function(){r.sendSocketMessage({cmd:"delete_env",prev_eid:r.state.envID,eid:r.state.modifyID})},r.saveEnv=function(){if(r.state.connected){r.updateLayout(r.state.layout);var e=r._envFieldRef.value,t={};Object.keys(r.state.panes).map(function(e){t[e]=JSON.parse(localStorage.getItem(r.keyLS(e)))}),r.sendSocketMessage({cmd:"save",data:t,prev_eid:r.state.envID,eid:e});var n=r.state.envList;n.indexOf(e)===-1&&n.push(e);var a=r.state.layoutLists;for(var o in n)a.has(n[o])||a.set(n[o],new Map([[E,new Map]]));r.setState({envList:n,layoutLists:a,envID:e})}},r.focusPane=function(e){r.setState({focusedPaneID:e})},r.resizePane=function(e,t,n){r.setState({layoutID:E}),r.focusPane(n.i),r.updateLayout(e)},r.movePane=function(e,t,n){r.setState({layoutID:E}),r.updateLayout(e)},r.rebin=function(e){e=e?e:r.state.layout;var t=r.state.layoutID;if(t!==E){var n=r.getCurrLayoutList(),a=n.get(r.state.layoutID);e=e.map(function(e,t){if(a.has(e.i)){var n=a.get(e.i);e.h=n[1],e.height=n[1],e.w=n[2],e.width=n[2]}return e})}var o=e.map(function(e,t){return{width:e.w,height:e.h}});return r._bin=new Bin.ShelfFirst(o,r.state.cols),e},r.relayout=function(e){var t=r.rebin(),n=h(t),a=Object.assign({},r.state.panes),o=r.state.filter,s=n.slice(),i=r.state.layoutID,l=r.getCurrLayoutList(),c=l.get(r.state.layoutID);n=n.sort(function(e,t){var n=(null!=a[e.i].title.match(o))-(null!=a[t.i].title.match(o));if(0!=n)return-n;if(i!==E){var r=c.has(e.i)?-c.get(e.i)[0]:1,l=c.has(t.i)?-c.get(t.i)[0]:1,u=l-r;if(0!=u)return u}return s.indexOf(e)-s.indexOf(t)});var u=n.map(function(e,t){var n=r._bin.position(t,r.state.cols);return!a[e.i],a[e.i].i=t,Object.assign({},e,n)});r.setState({panes:a}),r.state.panes=a,r.updateLayout(u)},r.toggleOnlineState=function(){r.state.connected?r.disconnect():r.connect()},r.updateLayout=function(e){r.setState({layout:e},function(e){r.state.layout.map(function(e,t){localStorage.setItem(r.keyLS(e.i),JSON.stringify(e))})}),r.state.layout=e},r.updateToLayout=function(e){r.setState({layoutID:e}),r.state.layoutID=e,e!==E&&(r.relayout(),r.relayout(),r.relayout())},r.onWidthChange=function(e,t){r.setState({cols:t,width:e},function(){r.relayout()})},s=n,o(r,s)}return r(t,e),l(t,[{key:"sendSocketMessage",value:function(e){if(this._socket){var t=JSON.stringify(e);return this._socket.send(t)}}},{key:"getCurrLayoutList",value:function(){return this.state.layoutLists.has(this.state.envID)?this.state.layoutLists.get(this.state.envID):new Map}},{key:"saveLayout",value:function(){for(var e=h(this.state.layout),t=new Map,n=0;n<e.length;n++){var a=this.state.panes[e[n].i],o=m(this.state.layout,a.id);t.set(e[n].i,[n,o.h,o.w])}var r=this.state.layoutLists;r.get(this.state.envID).set(this.state.saveText,t),this.setState({layoutLists:r,layoutID:this.state.saveText})}},{key:"deleteLayout",value:function(){var e=this.state.layoutLists;e.get(this.state.envID).delete(this.state.modifyID),this.setState({layoutLists:e})}},{key:"componentDidMount",value:function(){this.connect()}},{key:"openEnvModal",value:function(){this.setState({showEnvModal:!0,saveText:this.state.envID})}},{key:"closeEnvModal",value:function(){this.setState({showEnvModal:!1})}},{key:"openViewModal",value:function(){this.setState({showViewModal:!0,saveText:this.state.layoutID})}},{key:"closeViewModal",value:function(){this.setState({showViewModal:!1})}},{key:"renderEnvModal",value:function(){var e=this;return React.createElement(ReactModal,{isOpen:this.state.showEnvModal,onRequestClose:this.closeEnvModal.bind(this),contentLabel:"Environment Management Modal",ariaHideApp:!1,style:g},React.createElement("span",{className:"visdom-title"},"Manage Environments"),React.createElement("br",null),"Save or fork current environment:",React.createElement("br",null),React.createElement("div",{className:"form-inline"},React.createElement("input",{className:"form-control",type:"text",onChange:function(t){e.setState({saveText:t.target.value})},value:this.state.saveText,ref:function(t){return e._envFieldRef=t}}),React.createElement("button",{className:"btn btn-default",disabled:!this.state.connected,onClick:this.saveEnv},this.state.envList.indexOf(this.state.saveText)>=0?"save":"fork")),React.createElement("br",null),"Delete environment selected in dropdown:",React.createElement("br",null),React.createElement("div",{className:"form-inline"},React.createElement("select",{className:"form-control",disabled:!this.state.connected,onChange:function(t){e.setState({modifyID:t.target.value})},value:this.state.modifyID},this.state.envList.map(function(e){return React.createElement("option",{key:e,value:e},e)})),React.createElement("button",{className:"btn btn-default",disabled:!this.state.connected||!this.state.modifyID||"main"==this.state.modifyID,onClick:this.deleteEnv.bind(this)},"Delete")))}},{key:"renderViewModal",value:function(){var e=this;return React.createElement(ReactModal,{isOpen:this.state.showViewModal,onRequestClose:this.closeViewModal.bind(this),contentLabel:"Layout Views Management Modal",ariaHideApp:!1,style:g},React.createElement("span",{className:"visdom-title"},"Manage Views"),React.createElement("br",null),React.createElement("strong",null,"Currently these are only saved locally, and are lost on refresh"),React.createElement("br",null),React.createElement("em",null,"This feature is in beta, it's usually necessary to",React.createElement("br",null),"repack after selecting to restore your view"),React.createElement("br",null),"Save or fork current layout:",React.createElement("br",null),React.createElement("div",{className:"form-inline"},React.createElement("input",{className:"form-control",type:"text",onChange:function(t){e.setState({saveText:t.target.value})},value:this.state.saveText}),React.createElement("button",{className:"btn btn-default",disabled:!this.state.connected||this.state.saveText==E,onClick:this.saveLayout.bind(this)},this.getCurrLayoutList().has(this.state.saveText)?"save":"fork")),React.createElement("br",null),"Delete layout view selected in dropdown:",React.createElement("br",null),React.createElement("div",{className:"form-inline"},React.createElement("select",{className:"form-control",disabled:!this.state.connected,onChange:function(t){e.setState({modifyID:t.target.value})},value:this.state.modifyID},Array.from(this.getCurrLayoutList().keys()).map(function(e){return React.createElement("option",{key:e,value:e},e)})),React.createElement("button",{className:"btn btn-default",disabled:!this.state.connected||!this.state.modifyID||this.state.modifyID==E,onClick:this.deleteLayout.bind(this)},"Delete")))}},{key:"renderEnvControls",value:function(){var e=this,t=this.state.envList.map(function(t){var n="";return t==e.state.envID&&(n=React.createElement("span",null," ✓")),React.createElement("li",null,React.createElement("a",{href:"#",onClick:e.selectEnv.bind(e,t)},t,n))});return React.createElement("span",null,React.createElement("span",null,"Environment "),React.createElement("div",{className:"btn-group navbar-btn",role:"group","aria-label":"Environment:"},React.createElement("div",{className:"btn-group",role:"group"},React.createElement("button",{className:"btn btn-default dropdown-toggle",type:"button",id:"envDropdown","data-toggle":"dropdown","aria-haspopup":"true","aria-expanded":"true"},this.state.envID," ",React.createElement("span",{className:"caret"})),React.createElement("ul",{className:"dropdown-menu","aria-labelledby":"envDropdown"},t)),React.createElement("button",{"data-toggle":"tooltip",title:"Clear Current Environment","data-placement":"bottom",className:"btn btn-default",disabled:!this.state.connected,onClick:this.closeAllPanes},React.createElement("span",{className:"glyphicon glyphicon-erase"})),React.createElement("button",{"data-toggle":"tooltip",title:"Manage Environments","data-placement":"bottom",className:"btn btn-default",disabled:!this.state.connected,onClick:this.openEnvModal.bind(this)},React.createElement("span",{className:"glyphicon glyphicon-folder-open"}))))}},{key:"renderViewControls",value:function(){var e=this,t=Array.from(this.getCurrLayoutList().keys()).map(function(t){var n="";return t==e.state.layoutID&&(n=React.createElement("span",null," ✓")),React.createElement("li",null,React.createElement("a",{href:"#",onClick:e.updateToLayout.bind(e,t)},t,n))});return React.createElement("span",null,React.createElement("span",null,"View "),React.createElement("div",{className:"btn-group navbar-btn",role:"group","aria-label":"View:"},React.createElement("div",{className:"btn-group",role:"group"},React.createElement("button",{className:"btn btn-default dropdown-toggle",type:"button",id:"viewDropdown","data-toggle":"dropdown","aria-haspopup":"true","aria-expanded":"true"},this.state.layoutID," ",React.createElement("span",{className:"caret"})),React.createElement("ul",{className:"dropdown-menu","aria-labelledby":"viewDropdown"},t)),React.createElement("button",{"data-toggle":"tooltip",title:"Repack","data-placement":"bottom",className:"btn btn-default",onClick:function(t){e.relayout(),e.relayout()}},React.createElement("span",{className:"glyphicon glyphicon-th"})),React.createElement("button",{"data-toggle":"tooltip",title:"Manage Views","data-placement":"bottom",className:"btn btn-default",disabled:!this.state.connected,onClick:function(t){e.openViewModal()}},React.createElement("span",{className:"glyphicon glyphicon-folder-open"}))))}},{key:"renderFilterControl",value:function(){var e=this;return React.createElement("div",{className:"input-group navbar-btn"},React.createElement("input",{type:"text",className:"form-control",placeholder:"Filter text",onChange:function(t){e.setState({filterField:t.target.value})},value:this.state.filterField,ref:function(t){return e._filterFieldRef=t}}),React.createElement("span",{className:"input-group-btn"},React.createElement("button",{type:"button",className:"btn btn-default",disabled:!this.state.connected,onClick:function(t){e.setState({filter:e.state.filterField},function(){Object.keys(e.state.panes).map(function(t){e.focusPane(t)}),e.state.filter=e.state.filterField,e.relayout(),e.relayout()})}},"filter")))}},{key:"render",value:function(){var e=this,t=Object.keys(this.state.panes).map(function(t){var n=e.state.panes[t],a=b[n.type];if(!a)return console.error("unrecognized pane type: ",n),null;var o=m(e.state.layout,t);return React.createElement("div",{key:n.id,style:n.title.match(e.state.filter)?{}:{display:"none"}},React.createElement(a,i({},n,{key:n.id,onClose:e.closePane,onFocus:e.focusPane,onInflate:e.onInflate,isFocused:n.id===e.state.focusedPaneID,w:o.w,h:o.h})))}),n=this.renderEnvModal(),a=this.renderViewModal(),o=this.renderEnvControls(),r=this.renderViewControls(),s=this.renderFilterControl();return React.createElement("div",null,n,a,React.createElement("div",{className:"navbar-form navbar-default"},React.createElement("span",{className:"navbar-brand visdom-title"},"visdom"),o,"    ",r,React.createElement("span",{style:{float:"right"}},s,"  ",React.createElement("button",{className:classNames({btn:!0,"btn-success":this.state.connected,"btn-danger":!this.state.connected}),onClick:this.toggleOnlineState},this.state.connected?"online":"offline"))),React.createElement("div",null,React.createElement(d,{className:"layout",rowHeight:y,autoSize:!1,margin:[v,v],layout:this.state.layout,draggableHandle:".bar",onLayoutChange:this.handleLayoutChange,onWidthChange:this.onWidthChange,onResizeStop:this.resizePane,onDragStop:this.movePane},t)))}}]),t}(React.Component);document.addEventListener("DOMContentLoaded",s),$(document).ready(function(){$('[data-toggle="tooltip"]').tooltip({container:"body",delay:{show:600,hide:100},trigger:"hover"})})}]);