/**
 * Normalize window.location by removing specific path segments
 * and ensuring the pathname ends with a '/'.
 *
 * The pathname already carries the server's base_url, so deriving the
 * prefix from it keeps requests correct under -base_url deployments.
 */
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
