// Diagnostic only: inspect the watch's macOS Classic Bluetooth/HFP route.
// Build: clang -fobjc-arc -fblocks -framework Foundation -framework IOBluetooth \
//   scripts/probe_voice_route.m -o /tmp/stove-voice-route
// Run: /tmp/stove-voice-route XX:XX:XX:XX:XX:XX [--sdp] [--classic] [--hfp] [--rfcomm]
// --sdp queries Classic service records; --hfp attempts the HFP control link.
// --rfcomm checks whether the advertised hands-free channel opens, without sending AT commands.
// --classic requests an authenticated Classic baseband link and may show a pairing prompt.
// This never opens SCO audio, records microphone data, or changes BLE pairing.

#import <Foundation/Foundation.h>
#import <IOBluetooth/IOBluetooth.h>

@interface RouteProbe : NSObject <IOBluetoothHandsFreeDelegate, IOBluetoothRFCOMMChannelDelegate>
@property BOOL sdpDone;
@property BOOL hfpDone;
@property BOOL rfcommDone;
@end

@implementation RouteProbe
- (void)sdpQueryComplete:(IOBluetoothDevice *)device status:(IOReturn)status {
    printf("sdp_status=0x%08x service_count=%lu\n", status,
           (unsigned long)device.services.count);
    for (IOBluetoothSDPServiceRecord *service in device.services) {
        const char *name = service.getServiceName.UTF8String;
        BluetoothRFCOMMChannelID channel = 0;
        IOReturn channelStatus = [service getRFCOMMChannelID:&channel];
        printf("service=%s hands_free=%d audio_gateway=%d headset=%d channel=%u channel_status=0x%08x\n",
               name ?: "?", [service matchesUUID16:0x111e],
               [service matchesUUID16:0x111f], [service matchesUUID16:0x1108],
               channel, channelStatus);
    }
    fflush(stdout);
    self.sdpDone = YES;
}
- (void)handsFree:(IOBluetoothHandsFree *)gateway connected:(NSNumber *)status {
    printf("hfp_status=0x%08x connected=%d sco=%d\n",
           status.unsignedIntValue, gateway.isConnected, gateway.isSCOConnected);
    fflush(stdout);
    self.hfpDone = YES;
}
- (void)handsFree:(IOBluetoothHandsFree *)gateway disconnected:(NSNumber *)status {
    printf("hfp_disconnected=0x%08x\n", status.unsignedIntValue);
    fflush(stdout);
    self.hfpDone = YES;
}
- (void)rfcommChannelOpenComplete:(IOBluetoothRFCOMMChannel *)channel status:(IOReturn)status {
    printf("rfcomm_open_status=0x%08x open=%d\n", status, channel.isOpen);
    fflush(stdout);
    self.rfcommDone = YES;
}
- (void)rfcommChannelData:(IOBluetoothRFCOMMChannel *)channel data:(void *)data length:(size_t)length {
    // A hands-free control channel may contain private call data; report length only.
    printf("rfcomm_received_bytes=%zu\n", length);
    fflush(stdout);
}
- (void)rfcommChannelClosed:(IOBluetoothRFCOMMChannel *)channel {
    puts("rfcomm_closed");
    fflush(stdout);
    self.rfcommDone = YES;
}
@end

static BOOL waitFor(BOOL (^complete)(void), NSTimeInterval seconds) {
    NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:seconds];
    while (!complete() && deadline.timeIntervalSinceNow > 0) {
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.2]];
    }
    return complete();
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc < 2 || argc > 6) {
            fprintf(stderr, "usage: %s ADDRESS [--sdp] [--classic] [--hfp] [--rfcomm]\n", argv[0]);
            return 2;
        }
        NSString *address = [NSString stringWithUTF8String:argv[1]];
        BOOL querySDP = NO, connectClassic = NO, connectHFP = NO, connectRFCOMM = NO;
        for (int i = 2; i < argc; i++) {
            if (strcmp(argv[i], "--sdp") == 0) querySDP = YES;
            else if (strcmp(argv[i], "--classic") == 0) connectClassic = YES;
            else if (strcmp(argv[i], "--hfp") == 0) connectHFP = YES;
            else if (strcmp(argv[i], "--rfcomm") == 0) connectRFCOMM = YES;
            else { fprintf(stderr, "unknown option: %s\n", argv[i]); return 2; }
        }
        IOBluetoothDevice *device = [IOBluetoothDevice deviceWithAddressString:address];
        if (!device) { fputs("device_unavailable\n", stderr); return 1; }
        printf("paired=%d connected=%d link_type=%u encryption_mode=%u cached_services=%lu\n",
               device.isPaired, device.isConnected, [device getLinkType],
               [device getEncryptionMode], (unsigned long)device.services.count);
        RouteProbe *probe = [RouteProbe new];
        if (querySDP) {
            IOReturn status = [device performSDPQuery:probe];
            printf("sdp_query_started=0x%08x\n", status); fflush(stdout);
            if (status != kIOReturnSuccess || !waitFor(^BOOL { return probe.sdpDone; }, 18)) {
                puts("sdp_query_timeout_or_error");
            }
        }
        if (connectClassic) {
            IOReturn status = [device openConnection:nil withPageTimeout:kDefaultPageTimeout
                                 authenticationRequired:YES];
            printf("classic_open_status=0x%08x link_type=%u encryption_mode=%u\n",
                   status, [device getLinkType], [device getEncryptionMode]);
            fflush(stdout);
        }
        if (connectHFP) {
            IOBluetoothHandsFreeAudioGateway *gateway =
                [[IOBluetoothHandsFreeAudioGateway alloc] initWithDevice:device delegate:probe];
            printf("hfp_gateway_created=%d\n", gateway != nil); fflush(stdout);
            if (gateway) {
                [gateway connect];
                if (!waitFor(^BOOL { return probe.hfpDone; }, 20)) puts("hfp_connection_timeout");
                printf("hfp_final_connected=%d sco=%d\n", gateway.isConnected,
                       gateway.isSCOConnected);
                if (gateway.isConnected) [gateway disconnect];
            }
        }
        if (connectRFCOMM) {
            IOBluetoothRFCOMMChannel *channel = nil;
            IOReturn status = [device openRFCOMMChannelAsync:&channel withChannelID:1 delegate:probe];
            printf("rfcomm_open_started=0x%08x\n", status); fflush(stdout);
            if (status == kIOReturnSuccess && !waitFor(^BOOL { return probe.rfcommDone; }, 15)) {
                puts("rfcomm_open_timeout");
            }
            if (channel.isOpen) [channel closeChannel];
        }
    }
    return 0;
}
