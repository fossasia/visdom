export default function serverPath() {
  var pathname = window.location.pathname;
  if (pathname.indexOf('/env/') > -1) {
    pathname = pathname.split('/env/')[0];
  } else if (pathname.indexOf('/compare/') > -1) {
    pathname = pathname.split('/compare/')[0];
  }
  if (pathname.slice(-1) != '/') {
    pathname = pathname + '/';
  }
  return pathname;
}
