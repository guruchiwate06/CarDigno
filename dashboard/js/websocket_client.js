/**
 * CarDigno - Isolated WebSockets Transport Client
 * Manages WebSocket connection lifecycle, auto-reconnections, and incoming frame parsing.
 * ZERO DOM manipulation or rendering logic exists within this module.
 */

export class TelemetrySocket {
    /**
     * @param {string} url - WebSocket server endpoint (default: ws://127.0.0.1:8000/ws/telemetry)
     */
    constructor(url = 'ws://127.0.0.1:8000/ws/telemetry') {
        this.url = url;
        this.socket = null;
        this.isConnecting = false;
        this.reconnectTimer = null;
        this.reconnectInterval = 2000; // 2 seconds backoff
        this.maxReconnectInterval = 10000;
        
        // Event Listener Callbacks
        this.listeners = {
            open: [],
            close: [],
            error: [],
            message: []
        };
    }

    /**
     * Registers an event listener callback.
     * @param {string} event - 'open' | 'close' | 'error' | 'message'
     * @param {Function} callback
     */
    on(event, callback) {
        if (this.listeners[event]) {
            this.listeners[event].push(callback);
        }
    }

    /**
     * Emits event to all registered listeners.
     */
    emit(event, data) {
        if (this.listeners[event]) {
            this.listeners[event].forEach(cb => {
                try {
                    cb(data);
                } catch (err) {
                    console.error(`[TelemetrySocket] Callback error on '${event}':`, err);
                }
            });
        }
    }

    /**
     * Initiates connection to the WebSocket server.
     */
    connect() {
        if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
            return;
        }

        this.isConnecting = true;
        console.log(`[TelemetrySocket] Connecting to ${this.url}...`);

        try {
            this.socket = new WebSocket(this.url);

            this.socket.onopen = (evt) => {
                console.log('[TelemetrySocket] Connection established.');
                this.isConnecting = false;
                this.reconnectInterval = 2000; // Reset backoff
                this.emit('open', evt);
            };

            this.socket.onclose = (evt) => {
                console.warn('[TelemetrySocket] Connection closed.');
                this.isConnecting = false;
                this.emit('close', evt);
                this.scheduleReconnect();
            };

            this.socket.onerror = (err) => {
                console.error('[TelemetrySocket] Connection error:', err);
                this.emit('error', err);
            };

            this.socket.onmessage = (evt) => {
                try {
                    const data = JSON.parse(evt.data);
                    this.emit('message', data);
                } catch (err) {
                    console.error('[TelemetrySocket] Failed to parse message JSON:', err, evt.data);
                }
            };

        } catch (err) {
            console.error('[TelemetrySocket] Instantiation error:', err);
            this.isConnecting = false;
            this.scheduleReconnect();
        }
    }

    /**
     * Schedules automatic reconnect attempt.
     */
    scheduleReconnect() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }

        console.log(`[TelemetrySocket] Reconnecting in ${(this.reconnectInterval / 1000).toFixed(1)}s...`);
        this.reconnectTimer = setTimeout(() => {
            this.connect();
            // Exponential backoff up to max limit
            this.reconnectInterval = Math.min(this.maxReconnectInterval, this.reconnectInterval * 1.5);
        }, this.reconnectInterval);
    }

    /**
     * Sends raw text message over socket.
     * @param {string} msg 
     */
    send(msg) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(msg);
        }
    }

    /**
     * Closes socket connection.
     */
    close() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }
        if (this.socket) {
            this.socket.close();
        }
    }
}
