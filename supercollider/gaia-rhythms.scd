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
~gaiaLayers = IdentityDictionary.new;

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

SynthDef(\lightningGlass, {
    |out=0, freq=110, amp=0.35, duration=1.2, pan=0, depth=10, strength=0.5|
    var crackEnvelope, glassEnvelope, pitchContour, crack, shimmer, sparkle, lowPulse, signal;
    crackEnvelope = EnvGen.kr(Env.perc(0.001, 0.07, curve: -8));
    glassEnvelope = EnvGen.kr(
        Env.perc(0.003, duration.clip(0.4, 2.8), curve: -6),
        doneAction: Done.freeSelf
    );
    pitchContour = XLine.kr(
        freq * Rand(1.28, 1.52),
        freq * Rand(0.94, 1.08),
        duration.clip(0.35, 1.4)
    );
    crack = BPF.ar(
        WhiteNoise.ar,
        (pitchContour * 30).clip(1800, 9000),
        0.45,
        0.65
    ) * crackEnvelope;
    shimmer = SinOsc.ar(
        pitchContour * [1, 1.333, 1.618, 2.414] * [0.997, 1.011, 0.989, 1.019],
        0,
        [0.42, 0.26, 0.15, 0.08]
    ).sum;
    sparkle = Ringz.ar(
        Dust2.ar(8 + (strength * 28), 0.018),
        pitchContour * [2.7, 3.9],
        [0.055, 0.085]
    ).sum;
    lowPulse = SinOsc.ar((pitchContour * 0.5).max(42), 0, 0.09 * strength);
    signal = crack + ((shimmer + sparkle + lowPulse) * glassEnvelope);
    Out.ar(out, Pan2.ar(signal.tanh * amp * 0.52, pan));
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

SynthDef(\oceanSwellLayer, {
    |out=0, freq=110, amp=0.24, pan=0, depth=10, strength=0.5,
        transition=6, gate=1, release=3|
    var smoothFreq, smoothAmp, smoothPan, smoothStrength, swellPeriod;
    var swellCycle, envelope, surge, foam, undertow, signal;
    smoothFreq = Lag.kr(freq, transition.clip(1, 30));
    smoothAmp = Lag.kr(amp, transition.clip(1, 30));
    smoothPan = Lag.kr(pan, transition.clip(1, 30));
    smoothStrength = Lag.kr(strength, transition.clip(1, 30));
    swellPeriod = Lag.kr(depth.clip(4, 24), transition.clip(1, 30));
    swellCycle = LFTri.kr(swellPeriod.reciprocal, 3).range(0.22, 1).squared;
    envelope = EnvGen.kr(Env.asr(2.5, 1, release.max(1)), gate, doneAction: Done.freeSelf);
    surge = RLPF.ar(
        PinkNoise.ar(0.68),
        (smoothFreq * 3).clip(180, 900),
        0.2 + (smoothStrength * 0.2)
    ) * (0.38 + (swellCycle * 0.62));
    foam = BPF.ar(
        WhiteNoise.ar(0.2),
        (smoothFreq * 8).clip(700, 3200),
        0.5
    ) * swellCycle;
    undertow = SinOsc.ar((smoothFreq * 0.5).clip(45, 130), 0, 0.2);
    signal = (surge + foam + undertow) * envelope * smoothAmp;
    Out.ar(out, Pan2.ar(signal, smoothPan));
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
    var envelope, rainDensity, wash, drops, roofTone, distantBody, signal;
    envelope = EnvGen.kr(Env.linen(0.75, (duration - 1.5).max(0.4), 0.75, curve: -3), doneAction: Done.freeSelf);
    rainDensity = 12 + (strength * 95);
    wash = BPF.ar(PinkNoise.ar(0.55), 1700 + (strength * 2600), 0.7, 0.42);
    drops = Ringz.ar(
        Dust2.ar(rainDensity, 0.035 + (strength * 0.035)),
        [2400, 3600, 5200, 7100],
        [0.035, 0.028, 0.022, 0.017],
        [0.32, 0.24, 0.16, 0.1]
    ).sum;
    roofTone = HPF.ar(WhiteNoise.ar(0.11), 4800) * LFNoise2.kr(3.5).range(0.25, 1);
    distantBody = RLPF.ar(BrownNoise.ar(0.18), (freq * 2).clip(90, 320), 0.35);
    signal = (wash + drops + roofTone + distantBody) * envelope * amp;
    Out.ar(out, Pan2.ar(signal, pan));
}).add;

SynthDef(\stormRainLayer, {
    |out=0, freq=110, amp=0.22, pan=0, depth=30, strength=0.5,
        transition=6, gate=1, release=3|
    var smoothFreq, smoothAmp, smoothPan, smoothStrength, rainDensity;
    var envelope, wash, drops, surface, distantBody, signal;
    smoothFreq = Lag.kr(freq, transition.clip(1, 30));
    smoothAmp = Lag.kr(amp, transition.clip(1, 30));
    smoothPan = Lag.kr(pan, transition.clip(1, 30));
    smoothStrength = Lag.kr(strength, transition.clip(1, 30));
    rainDensity = 10 + (smoothStrength * 110);
    envelope = EnvGen.kr(Env.asr(2.5, 1, release.max(1)), gate, doneAction: Done.freeSelf);
    wash = BPF.ar(
        PinkNoise.ar(0.58),
        1500 + (smoothStrength * 3000),
        0.72,
        0.38 + (smoothStrength * 0.18)
    );
    drops = Ringz.ar(
        Dust2.ar(rainDensity, 0.03 + (smoothStrength * 0.04)),
        [2300, 3400, 4900, 6800],
        [0.038, 0.03, 0.023, 0.018],
        [0.32, 0.24, 0.16, 0.1]
    ).sum;
    surface = HPF.ar(WhiteNoise.ar(0.1), 4600) * LFNoise2.kr(3.2).range(0.2, 1);
    distantBody = RLPF.ar(BrownNoise.ar(0.2), (smoothFreq * 2).clip(90, 340), 0.36);
    signal = (wash + drops + surface + distantBody) * envelope * smoothAmp;
    Out.ar(out, Pan2.ar(signal, smoothPan));
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
        if(instrument == "lightning_glass", { synthName = \lightningGlass });
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

    OSCdef(\gaiaLayer, {
        |msg, time, addr, recvPort|
        var eventId = msg[1];
        var kind = msg[2].asString;
        var instrument = msg[3].asString;
        var pitch = msg[4].asFloat;
        var velocity = msg[5].asFloat;
        var transition = msg[6].asFloat;
        var pan = msg[7].asFloat;
        var strength = msg[8].asFloat;
        var depth = msg[12].asFloat;
        var key = kind.asSymbol;
        var layer = ~gaiaLayers[key];
        var synthName;

        if(instrument == "ocean_swell", { synthName = \oceanSwellLayer });
        if(instrument == "storm_potential", { synthName = \stormRainLayer });
        if(synthName.notNil, {
            if(layer.isNil, {
                layer = Synth(synthName, [
                    \freq, pitch.midicps,
                    \amp, velocity.linlin(20, 127, 0.06, 0.34),
                    \transition, transition,
                    \pan, pan,
                    \depth, depth,
                    \strength, strength
                ]);
                ~gaiaLayers[key] = layer;
            }, {
                layer.set(
                    \freq, pitch.midicps,
                    \amp, velocity.linlin(20, 127, 0.06, 0.34),
                    \transition, transition,
                    \pan, pan,
                    \depth, depth,
                    \strength, strength
                );
            });
            ("Gaia layer " ++ kind ++ " updated from " ++ eventId).postln;
        });
    }, '/gaia/layer', recvPort: oscPort);

    OSCdef(\gaiaLayerStop, {
        |msg, time, addr, recvPort|
        var key = msg[1].asString.asSymbol;
        var release = msg[2].asFloat;
        var layer = ~gaiaLayers.removeAt(key);
        if(layer.notNil, { layer.set(\release, release, \gate, 0) });
        ("Gaia layer " ++ key ++ " released").postln;
    }, '/gaia/layer/stop', recvPort: oscPort);

    ("Gaia Rhythms listening for OSC on UDP " ++ oscPort).postln;
});
)
