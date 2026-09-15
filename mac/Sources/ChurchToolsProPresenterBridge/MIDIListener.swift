import CoreMIDI
import Foundation

struct MIDINoteMessage {
    let channel: Int
    let note: Int
    let velocity: Int
}

final class MIDIListener {
    private let sink = MIDIMessageSink()
    private var client = MIDIClientRef()
    private var destination = MIDIEndpointRef()

    init(name: String = "ChurchTools Bridge") throws {
        var status = MIDIClientCreateWithBlock(name as CFString, &client) { _ in }
        guard status == noErr else { throw MIDIListenerError.coreMIDI(status) }

        status = MIDIDestinationCreateWithBlock(client, name as CFString, &destination) { [sink] packetList, _ in
            sink.receive(packetList)
        }
        guard status == noErr else {
            MIDIClientDispose(client)
            throw MIDIListenerError.coreMIDI(status)
        }
    }

    deinit {
        MIDIEndpointDispose(destination)
        MIDIClientDispose(client)
    }

    func messages() -> AsyncStream<MIDINoteMessage> {
        AsyncStream { continuation in
            sink.continuation = continuation
            continuation.onTermination = { [sink] _ in sink.continuation = nil }
        }
    }
}

private final class MIDIMessageSink: @unchecked Sendable {
    private let lock = NSLock()
    private var storedContinuation: AsyncStream<MIDINoteMessage>.Continuation?

    var continuation: AsyncStream<MIDINoteMessage>.Continuation? {
        get { lock.withLock { storedContinuation } }
        set { lock.withLock { storedContinuation = newValue } }
    }

    func receive(_ packetList: UnsafePointer<MIDIPacketList>) {
        var packet = packetList.pointee.packet
        for _ in 0..<packetList.pointee.numPackets {
            let bytes = withUnsafeBytes(of: packet.data) { Array($0.prefix(Int(packet.length))) }
            parse(bytes)
            packet = MIDIPacketNext(&packet).pointee
        }
    }

    private func parse(_ bytes: [UInt8]) {
        var index = 0
        while index + 2 < bytes.count {
            let status = bytes[index]
            guard status & 0xF0 == 0x90 else {
                index += 1
                continue
            }
            let velocity = Int(bytes[index + 2])
            if velocity > 0 {
                continuation?.yield(MIDINoteMessage(
                    channel: Int(status & 0x0F) + 1,
                    note: Int(bytes[index + 1]),
                    velocity: velocity
                ))
            }
            index += 3
        }
    }
}

enum MIDIListenerError: LocalizedError {
    case coreMIDI(OSStatus)

    var errorDescription: String? {
        switch self {
        case .coreMIDI(let status): return "CoreMIDI-Fehler \(status)"
        }
    }
}
