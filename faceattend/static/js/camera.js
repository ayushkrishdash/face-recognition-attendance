// Thin wrapper around getUserMedia. Frames are captured in the browser and sent over HTTPS to the server.
window.CameraKit = (() => {
  let stream = null;
  const MESSAGES = {
    NotAllowedError: "Camera permission was denied. Allow camera access in your browser settings, then try again.",
    SecurityError: "The camera needs a secure connection. Open the app on localhost or over HTTPS.",
    NotFoundError: "No camera was found on this device.",
    NotReadableError: "The camera is being used by another application. Close it and try again.",
    OverconstrainedError: "This camera does not support the requested resolution.",
    AbortError: "The camera could not start. Please try again.",
  };

  function errorMessage(err) {
    return MESSAGES[err?.name] || `Camera error: ${err?.message || "unknown problem"}`;
  }

  async function start(videoEl) {
    if (stream) stop();
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      const err = new Error("insecure context");
      err.name = "SecurityError";
      throw err;
    }
    stream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: "user", width: { ideal: 640 }, height: { ideal: 480 } },
      audio: false,
    });
    videoEl.srcObject = stream;
    videoEl.muted = true;
    await videoEl.play();
    return stream;
  }

  function stop() {
    if (stream) stream.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  function capture(videoEl, quality = 0.9) {
    if (!videoEl.videoWidth) return Promise.resolve(null);
    const canvas = document.createElement("canvas");
    canvas.width = videoEl.videoWidth;
    canvas.height = videoEl.videoHeight;
    canvas.getContext("2d").drawImage(videoEl, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
  }

  window.addEventListener("pagehide", stop);
  return { start, stop, capture, errorMessage, isRunning: () => !!stream };
})();
