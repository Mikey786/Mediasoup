// mediasoup_server_nodejs/server.js
const express = require('express');
const http = require('http');
const mediasoup = require('mediasoup');
const cors = require('cors');
const config = require('./config'); 

const app = express();
app.use(cors()); 
app.use(express.json()); 
const httpServer = http.createServer(app);

let workers = [];
let nextWorkerIdx = 0;
const rooms = {}; 

async function createWorker() {
    const worker = await mediasoup.createWorker(config.mediasoup.workerSettings);
    console.log(`Node.js: Mediasoup worker ${worker.pid} created`);
    worker.on('died', (error) => {
        console.error(`Node.js: Mediasoup worker ${worker.pid} died:`, error);
        process.exit(1); 
    });
    return worker;
}

async function getMediasoupWorker() {
    if (workers.length === 0) throw new Error("No Mediasoup workers available.");
    const worker = workers[nextWorkerIdx];
    nextWorkerIdx = (nextWorkerIdx + 1) % workers.length;
    return worker;
}

async function getOrCreateRoom(roomId) {
    if (rooms[roomId]) return rooms[roomId];
    console.log(`Node.js: Creating new room: ${roomId}`);
    const worker = await getMediasoupWorker();
    const router = await worker.createRouter(config.mediasoup.routerOptions);
    console.log(`Node.js: Router created for room ${roomId} [id:${router.id}] on worker ${worker.pid}`);
    const room = { id: roomId, router, clients: new Map() };
    rooms[roomId] = room;
    router.on('workerclose', () => { delete rooms[roomId]; console.log(`Node.js: Router for room ${roomId} closed.`); });
    return room;
}

function getClientData(room, clientId) {
    if (!room.clients.has(clientId)) {
        console.log(`Node.js: Creating client data for ${clientId} in room ${room.id}`);
        room.clients.set(clientId, { transports: new Map(), producers: new Map(), consumers: new Map() });
    }
    return room.clients.get(clientId);
}

app.get('/rooms/:roomId/router-rtp-capabilities', async (req, res) => {
    const { roomId } = req.params;
    console.log(`Node.js: GET /router-rtp-capabilities for room ${roomId}`);
    try { const room = await getOrCreateRoom(roomId); res.json(room.router.rtpCapabilities); }
    catch (error) { console.error(`Node.js: Error GET /router-rtp-capabilities for room ${roomId}:`, error.message); res.status(500).json({ error: error.message }); }
});

app.post('/rooms/:roomId/clients/:clientId/transports', async (req, res) => {
    const { roomId, clientId } = req.params;
    console.log(`Node.js: POST /transports for client ${clientId} in room ${roomId}`);
    try {
        const room = await getOrCreateRoom(roomId); const clientData = getClientData(room, clientId);
        const transport = await room.router.createWebRtcTransport({...config.mediasoup.webRtcTransportOptions, appData: { roomId, clientId, dtlsConnected: false }});
        clientData.transports.set(transport.id, transport);
        console.log(`Node.js: Transport created for ${clientId} [id:${transport.id}]`);
        res.json({ id: transport.id, iceParameters: transport.iceParameters, iceCandidates: transport.iceCandidates, dtlsParameters: transport.dtlsParameters, sctpParameters: transport.sctpParameters });
    } catch (error) { console.error(`Node.js: Error POST /transports for ${clientId} in ${roomId}:`, error.message); res.status(500).json({ error: error.message }); }
});

app.post('/rooms/:roomId/clients/:clientId/transports/:transportId/connect', async (req, res) => {
    const { roomId, clientId, transportId } = req.params; const { dtlsParameters } = req.body;
    console.log(`Node.js: POST /connect for transport ${transportId}. Client: ${clientId}. DtlsParameters role: ${dtlsParameters?.role}`);
    try {
        const room = rooms[roomId]; if (!room) { return res.status(404).json({ error: `Room ${roomId} not found` });}
        const clientData = room.clients.get(clientId); if (!clientData) { return res.status(404).json({ error: `Client ${clientId} not found` });}
        const transport = clientData.transports.get(transportId); if (!transport) { return res.status(404).json({ error: `Transport ${transportId} not found` });}
        if (transport.appData.dtlsConnected) { console.warn(`Node.js: Transport ${transportId} already DTLS connected. Ignoring duplicate POST /connect.`); return res.sendStatus(200); }
        await transport.connect({ dtlsParameters }); transport.appData.dtlsConnected = true;
        console.log(`Node.js: Transport DTLS connected for ${clientId} [id:${transportId}]`);
        res.sendStatus(200); 
    } catch (error) { console.error(`Node.js: Error POST /connect transport ${transportId} for ${clientId}:`, error.message); res.status(500).json({ error: error.message }); }
});

app.post('/rooms/:roomId/clients/:clientId/transports/:transportId/produce', async (req, res) => {
    const { roomId, clientId, transportId } = req.params; const { kind, rtpParameters, appData } = req.body;
    console.log(`Node.js: POST /produce for ${clientId}, kind: ${kind}. Transport: ${transportId}. AppData:`, appData);
    try {
        const room = rooms[roomId]; if (!room) return res.status(404).json({ error: `Room ${roomId} not found` });
        const clientData = room.clients.get(clientId); if (!clientData) return res.status(404).json({ error: `Client ${clientId} not found` });
        const transport = clientData.transports.get(transportId); if (!transport) return res.status(404).json({ error: `Transport ${transportId} not found` });
        if (!transport.appData.dtlsConnected) { return res.status(400).json({ error: "Transport not DTLS connected for producing." }); }
        const producer = await transport.produce({ kind, rtpParameters, appData: { ...appData, roomId, clientId }});
        clientData.producers.set(producer.id, producer);
        producer.on('transportclose', () => { clientData.producers.delete(producer.id); console.log(`Node.js: Producer ${producer.id} transport closed.`); });
        producer.on('close', () => { clientData.producers.delete(producer.id); console.log(`Node.js: Producer ${producer.id} explicitly closed.`); });
        console.log(`Node.js: Producer created for ${clientId} [id:${producer.id}, kind:${kind}]`);
        res.json({ id: producer.id });
    } catch (error) { console.error(`Node.js: Error POST /produce for ${clientId} [transportId:${transportId}, kind:${kind}]:`, error.message); res.status(500).json({ error: error.message }); }
});

app.get('/rooms/:roomId/clients/:clientId/producers', (req, res) => {
    const { roomId, clientId } = req.params;
    console.log(`Node.js: GET /producers for client ${clientId} in room ${roomId}`);
    const room = rooms[roomId]; if (!room) return res.status(404).json({ error: `Room ${roomId} not found` });
    const clientData = room.clients.get(clientId); 
    if (!clientData || !clientData.producers) { console.log(`Node.js: Client ${clientId} (or producers map) not found for GET /producers. Returning [].`); return res.json([]); }
    const activeProducers = [];
    clientData.producers.forEach(p => { if (!p.closed) activeProducers.push({ producerId: p.id, kind: p.kind, appData: p.appData }); });
    console.log(`Node.js: Sending active producers for ${clientId} in room ${roomId}:`, activeProducers);
    res.json(activeProducers);
});

app.post('/rooms/:roomId/clients/:clientId/transports/:transportId/consume', async (req, res) => {
    const { roomId, clientId, transportId } = req.params; const { producerId, rtpCapabilities, appData } = req.body;
    console.log(`Node.js: POST /consume for ${clientId} (transport: ${transportId}) to consume producer ${producerId}`);
    try {
        const room = rooms[roomId]; if (!room) return res.status(404).json({ error: `Room ${roomId} not found` });
        const consumingClientData = room.clients.get(clientId); if (!consumingClientData) return res.status(404).json({ error: `Consuming client ${clientId} not found` });
        const recvTransport = consumingClientData.transports.get(transportId); if (!recvTransport) return res.status(404).json({ error: `Receiving transport ${transportId} not found` });
        if (!recvTransport.appData.dtlsConnected) { return res.status(400).json({ error: "Receiving transport not DTLS connected." }); }
        let producerToConsume = null;
        for (const [, rcd] of room.clients) { if (rcd.producers && rcd.producers.has(producerId)) { producerToConsume = rcd.producers.get(producerId); break; } }
        if (!producerToConsume || producerToConsume.closed) { return res.status(404).json({ error: `Producer ${producerId} not found or closed` }); }
        if (!room.router.canConsume({ producerId: producerToConsume.id, rtpCapabilities })) { return res.status(400).json({ error: 'Client cannot consume producer' }); }
        const consumer = await recvTransport.consume({ producerId: producerToConsume.id, rtpCapabilities, paused: producerToConsume.kind === 'video', appData: { ...appData, roomId, consumingClientId: clientId, producerOwnerId: producerToConsume.appData.clientId }});
        consumingClientData.consumers.set(consumer.id, consumer);
        consumer.on('transportclose', () => { consumingClientData.consumers.delete(consumer.id); console.log(`Node.js: Consumer ${consumer.id} transport closed.`); });
        consumer.on('producerclose', () => { consumingClientData.consumers.delete(consumer.id); console.log(`Node.js: Consumer ${consumer.id} producer closed.`); });
        consumer.on('close', () => { consumingClientData.consumers.delete(consumer.id); console.log(`Node.js: Consumer ${consumer.id} explicitly closed.`); });
        console.log(`Node.js: Consumer created for ${clientId} consuming ${producerId} [consumer_id:${consumer.id}]`);
        res.json({ id: consumer.id, producerId: consumer.producerId, kind: consumer.kind, rtpParameters: consumer.rtpParameters, paused: consumer.appData.producerPaused || consumer.paused, appData: consumer.appData });
    } catch (error) { console.error(`Node.js: Error POST /consume for ${clientId} [producerId:${producerId}]:`, error.message); res.status(500).json({ error: error.message }); }
});

app.post('/rooms/:roomId/clients/:clientId/consumers/:consumerId/resume', async (req, res) => {
    const { roomId, clientId, consumerId } = req.params;
    console.log(`Node.js: POST /resume-consumer for consumer ${consumerId} by client ${clientId}`);
    try {
        const room = rooms[roomId]; if (!room) return res.status(404).json({ error: `Room ${roomId} not found` });
        const clientData = room.clients.get(clientId); if (!clientData) return res.status(404).json({ error: `Client ${clientId} not found` });
        const consumer = clientData.consumers.get(consumerId); if (!consumer) return res.status(404).json({ error: `Consumer ${consumerId} not found` });
        if (consumer.closed) { return res.status(400).json({error: "Consumer is closed."}); }
        if (!consumer.paused && !consumer.producerPaused) { console.warn(`Node.js: Consumer ${consumerId} already resumed.`); return res.sendStatus(200); }
        await consumer.resume(); console.log(`Node.js: Consumer resumed [id:${consumerId}]`);
        res.sendStatus(200); 
    } catch (error) { console.error(`Node.js: Error POST /resume-consumer ${consumerId}:`, error.message); res.status(500).json({ error: error.message }); }
});

app.post('/rooms/:roomId/clients/:clientId/disconnected', (req, res) => {
    const { roomId, clientId } = req.params;
    console.log(`Node.js: POST /client-disconnected for ${clientId} in room ${roomId}`);
    const room = rooms[roomId];
    if (room) {
        const clientData = room.clients.get(clientId); 
        if (clientData) {
            console.log(`Node.js: Cleaning Mediasoup resources for client ${clientId}`);
            if(clientData.producers) clientData.producers.forEach(p => { console.log(`Node.js: Closing producer ${p.id}`); p.close(); });
            if(clientData.consumers) clientData.consumers.forEach(c => { console.log(`Node.js: Closing consumer ${c.id}`); c.close(); });
            if(clientData.transports) clientData.transports.forEach(t => { console.log(`Node.js: Closing transport ${t.id}`); t.close(); });
            room.clients.delete(clientId); console.log(`Node.js: Client ${clientId} data removed from room ${roomId}.`);
        }
        if (room.clients.size === 0) {
            console.log(`Node.js: Room ${roomId} empty, closing router [id:${room.router.id}].`);
            room.router.close(); delete rooms[roomId]; console.log(`Node.js: Room ${roomId} object deleted.`);
        }
    } else { console.log(`Node.js: Room ${roomId} not found for disconnect of ${clientId}.`); }
    res.send('OK'); // Explicit "OK" text response
});

(async () => {
    try {
        console.log('Node.js: Starting Mediasoup workers...');
        if (config.mediasoup.numWorkers < 1) { config.mediasoup.numWorkers = 1; }
        for (let i = 0; i < config.mediasoup.numWorkers; i++) { workers.push(await createWorker()); }
        if (workers.length === 0) { throw new Error("Node.js: No Mediasoup workers started."); }
        console.log(`Node.js: Total ${workers.length} Mediasoup workers started.`);
        httpServer.listen(config.listenPort, config.listenIp, () => {
            console.log(`Mediasoup Node.js server listening on http://${config.listenIp}:${config.listenPort}`);
        });
    } catch (error) { console.error('Node.js: Failed to start Mediasoup application:', error); process.exit(1); }
})();