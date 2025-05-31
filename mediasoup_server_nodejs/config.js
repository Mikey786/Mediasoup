// mediasoup_server_nodejs/config.js
const os = require('os');

module.exports = {
    listenIp: '0.0.0.0', // For the HTTP server that Django talks to
    listenPort: 4000,
    mediasoup: {
        // Use at least 1 worker, or based on CPU cores.
        // Ensure os.cpus() is available and returns a valid array.
        numWorkers: Math.max(1, Object.keys(os.cpus() || {}).length), 
        workerSettings: {
            logLevel: 'warn',
            logTags: [
                'info',
                'ice',
                'dtls',
                'rtp',
                'srtp',
                'rtcp',
                // 'rtx', // Can be noisy
                // 'bwe', // Can be noisy
                // 'score', // Can be noisy
                // 'simulcast', // Add if using simulcast
                // 'svc' // Add if using SVC
            ],
            rtcMinPort: 40000,
            rtcMaxPort: 49999
        },
        routerOptions: {
            mediaCodecs: [
                {
                    kind: 'audio',
                    mimeType: 'audio/opus',
                    clockRate: 48000,
                    channels: 2
                },
                {
                    kind: 'video',
                    mimeType: 'video/VP8', // VP8 is widely supported
                    clockRate: 90000,
                    parameters: {
                        'x-google-start-bitrate': 1000
                    }
                },
                // Example for H264 (ensure client supports it and you handle profiles if needed)
                // {
                //   kind       : 'video',
                //   mimeType   : 'video/H264',
                //   clockRate  : 90000,
                //   parameters :
                //   {
                //     'packetization-mode'      : 1,
                //     'profile-level-id'        : '42e01f', // Baseline profile, level 3.1
                //     'level-asymmetry-allowed' : 1,
                //     // 'x-google-start-bitrate'  : 1000 // Optional
                //   }
                // },
            ]
        },
        webRtcTransportOptions: {
            listenIps: [
                {
                    ip: '0.0.0.0',         // Mediasoup will bind its media sockets to this IP.
                                             // '0.0.0.0' listens on all available IPv4 interfaces.
                                             // '::' listens on all available IPv6 interfaces.
                    announcedIp: null        // <<< CHANGED HERE
                                             // If null, Mediasoup tries to auto-detect.
                                             // For listenIp '127.0.0.1', announcedIp will be '127.0.0.1'.
                                             // For listenIp '0.0.0.0', it will try to pick a private/public LAN IP.
                                             // For production on a public server, this MUST be the server's public IP.
                }
            ],
            initialAvailableOutgoingBitrate: 1000000, // 1 Mbps
            // maxSctpMessageSize: 262144, // Only if using DataChannels with large messages
            enableUdp: true,
            enableTcp: false,  // Good for fallback if UDP is blocked, but adds complexity for ICE.
                              // For testing, keeping it true helps see if TCP candidates are formed.
            preferUdp: true,
            appData: { 
                // You can put any custom data here that you want associated with transports
                // e.g., { info: "default_webrtc_transport_options" }
            }
        }
    }
};