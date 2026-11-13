/* Campus X - shared API helper.
   If the page is opened from the Flask server (port 5000) requests are same-origin.
   If you serve the frontend elsewhere (e.g. port 5500) it calls the backend on port 5000
   of the same host. Override with:  window.CAMPUSX_API = "https://your-api-host";  */
(function () {
  var p = location.port;
  var API = window.CAMPUSX_API !== undefined ? window.CAMPUSX_API
    : (p === "" || p === "5000") ? "" : location.protocol + "//" + location.hostname + ":5000";

  async function request(path, opts) {
    opts = opts || {};
    var init = { method: opts.method || "GET", credentials: "include", headers: {} };
    if (opts.json !== undefined) {
      init.method = opts.method || "POST";
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(opts.json);
    } else if (opts.form) {
      init.method = opts.method || "POST";
      init.body = opts.form;
    }
    var res, data;
    try { res = await fetch(API + path, init); }
    catch (e) {
      var ne = new Error("Unable to reach the Campus X server. Make sure the backend is running.");
      ne.status = 0; throw ne;
    }
    try { data = await res.json(); } catch (e) { data = {}; }
    if (!res.ok || data.success === false) {
      var err = new Error(data.message || "Something went wrong. Please try again.");
      err.status = res.status; err.data = data; throw err;
    }
    return data;
  }

  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[c];
    });
  }

  window.cx = {
    API: API, request: request, esc: esc,
    url: function (u) { return !u ? "" : /^https?:/.test(u) ? u : API + u; }
  };
})();
