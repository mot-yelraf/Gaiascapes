// Gaia Rhythms SuperCollider receiver.
// Python sends /gaia/cue to UDP 57130 by default.
(
var oscPort = 57130;
var audioDevice = "GAIA_RHYTHMS_AUDIO_DEVICE".getenv;

thisProcess.openUDPPort(oscPort);

if(audioDevice.notNil and: { audioDevice.size > 0 }, {
    s.options.numInputBusChannels = 0;
    s.options.outDevice = audioDevice;
    ("Gaia Rhythms selected audio output: " ++ audioDevice).postln;
});

s.waitForBoot({
SynthDef(\earthquake, {
    |out=0, freq=110, amp=0.35, duration=0.8, pan=0, depth=10, strength=0.5|
    var rumbleFreq, tremor, groundTone, body, impact, envelope, signal, outputSignal;
    rumbleFreq = (freq * 0.5).clip(58, 118);
    envelope = EnvGen.kr(Env.perc(0.35, duration.max(1.5), curve: -3), doneAction: Done.freeSelf);
    tremor = RLPF.ar(BrownNoise.ar(1), rumbleFreq * 2.4, 0.3, 0.85);
    groundTone = SinOsc.ar(rumbleFreq * [1, 1.012], 0, [0.55, 0.38]).sum;
    body = SinOsc.ar(freq * [0.75, 1], 0, [0.22, 0.12]).sum;
    impact = BPF.ar(PinkNoise.ar, (rumbleFreq * 3).clip(180, 380), 0.65, 0.18) * strength;
    signal = ((tremor + groundTone + body + impact) * 0.72).tanh;
    outputSignal = LeakDC.ar(signal) * envelope * amp * 1.25;
    Out.ar(out, Pan2.ar(outputSignal, pan));
}).add;

SynthDef(\seismicBells, {
    |out=0, freq=110, amp=0.35, duration=0.8, pan=0, depth=10, strength=0.5|
    var envelope, shimmer, lowBell;
    envelope = EnvGen.kr(Env.perc(0.004, duration.max(0.18) * 2.4, curve: -5), doneAction: Done.freeSelf);
    shimmer = SinOsc.ar(freq * [1, 1.507, 2.013], 0, [0.5, 0.25, 0.12]).sum;
    lowBell = SinOsc.ar((freq * 0.5).max(28), 0, 0.24 + (strength * 0.12));
    Out.ar(out, Pan2.ar((shimmer + lowBell) * envelope * amp, pan));
}).add;

SynthDef(\tectonicDrone, {
    |out=0, freq=110, amp=0.35, duration=0.8, pan=0, depth=10, strength=0.5|
    var envelope, drift, rumble;
    envelope = EnvGen.kr(Env.linen(0.08, duration.max(0.4), 0.7, curve: -3), doneAction: Done.freeSelf);
    drift = VarSaw.ar(freq * [0.25, 0.251], 0, 0.22, 0.16).sum;
    rumble = RLPF.ar(BrownNoise.ar(0.42), (freq * 1.7).clip(45, 420), 0.28 + (strength * 0.2));
    Out.ar(out, Pan2.ar((drift + rumble) * envelope * amp, pan));
}).add;

SynthDef(\oceanSwell, {
    |out=0, freq=110, amp=0.35, duration=0.8, pan=0, depth=10, strength=0.5|
    var envelope, surge, foam, undertow;
    envelope = EnvGen.kr(Env.linen(0.75, (duration - 1.5).max(0.4), 0.75, curve: -2), doneAction: Done.freeSelf);
    surge = RLPF.ar(PinkNoise.ar(0.7), (freq * 3).clip(180, 900), 0.22 + (strength * 0.18));
    foam = BPF.ar(WhiteNoise.ar(0.22), (freq * 8).clip(700, 3200), 0.5);
    undertow = SinOsc.ar((freq * 0.5).clip(45, 130), 0, 0.22);
    Out.ar(out, Pan2.ar((surge + foam + undertow) * envelope * amp, pan));
}).add;

SynthDef(\tidalBell, {
    |out=0, freq=110, amp=0.35, duration=0.8, pan=0, depth=10, strength=0.5|
    var envelope, bell;
    envelope = EnvGen.kr(Env.perc(0.08, (duration - 0.08).max(1.0), curve: -4), doneAction: Done.freeSelf);
    bell = SinOsc.ar(freq * [0.5, 1, 1.498, 2.01], 0, [0.28, 0.36, 0.17, 0.08]).sum;
    Out.ar(out, Pan2.ar(bell * envelope * amp, pan));
}).add;

SynthDef(\stormPotential, {
    |out=0, freq=110, amp=0.35, duration=0.8, pan=0, depth=10, strength=0.5|
    var envelope, air, charge, distant;
    envelope = EnvGen.kr(Env.linen(0.75, (duration - 1.5).max(0.4), 0.75, curve: -3), doneAction: Done.freeSelf);
    air = BPF.ar(PinkNoise.ar(0.55), (freq * 5).clip(350, 1800), 0.35);
    charge = Ringz.ar(Dust2.ar(4 + (strength * 14), 0.12), (freq * [2.1, 3.2]).clip(180, 1600), 0.22).sum;
    distant = RLPF.ar(BrownNoise.ar(0.2), (freq * 2).clip(90, 420), 0.3);
    Out.ar(out, Pan2.ar((air + charge + distant) * envelope * amp, pan));
}).add;

    s.sync;
    OSCdef(\earthCue, {
        |msg, time, addr, recvPort|
        var eventId = msg[1];
        var kind = msg[2].asString;
        var instrument = msg[3].asString;
        var pitch = msg[4].asFloat;
        var velocity = msg[5].asFloat;
        var duration = msg[6].asFloat;
        var pan = msg[7].asFloat;
        var strength = msg[8].asFloat;
        var longitude = msg[9].asFloat;
        var latitude = msg[10].asFloat;
        var magnitude = msg[11].asFloat;
        var depth = msg[12].asFloat;
        var synthName = \earthquake;

        if(instrument == "seismic_bells", { synthName = \seismicBells });
        if(instrument == "tectonic_drone", { synthName = \tectonicDrone });
        if(instrument == "ocean_swell", { synthName = \oceanSwell });
        if(instrument == "tidal_bell", { synthName = \tidalBell });
        if(instrument == "storm_potential", { synthName = \stormPotential });
        Synth(synthName, [
            \freq, pitch.midicps,
            \amp, velocity.linlin(20, 127, 0.08, 0.58),
            \duration, duration,
            \pan, pan,
            \depth, depth,
            \strength, strength
        ]);
        ("Gaia cue " ++ eventId ++ " -> " ++ instrument ++ " M" ++ magnitude.round(0.1)
            ++ " @ " ++ latitude.round(0.01) ++ ", "
            ++ longitude.round(0.01)).postln;
    }, '/gaia/cue', recvPort: oscPort);

    ("Gaia Rhythms listening for OSC on UDP " ++ oscPort).postln;
});
)
