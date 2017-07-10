---

layout: post
title: MakerBot, Clones and GPX
author: markwal
date: 2017-07-09 17:01:00 -0700
excerpt: Talking to MakerBots and their clones requires a translator plugin, GPX.
  There are a few gotchas that can crop up when using the GPX plugin with
  OctoPrint especially when doing one print after another. The fix is simple
  but the reason is a bit complicated.

---

# Five Things

Five things you need to do for OctoPrint to work well with your Sailfish or
MakerBot clone (QIDI tech, FlashForge Creator Pro, Wanhao Duplicator 4, etc.):

## Install the GPX plugin

You need the GPX plugin to talk x3g protocol to Sailfish. Install it via the
Plugin Manager in OctoPrint Settings. Search for "GPX".

## Set and save the GPX plugin settings

After GPX is intalled and OctoPrint restarted, bring up OctoPrint Settings and
choose GPX. Pick your machine type (probably Replicator 1 Dual even if your
printer manufacturer claims it's a Replicator 2 since there aren't any
Replicator 2 clones). Choose the "RepRap" flavor for gcode (unless you're using
MakerBot Desktop or RepG to slice). Also, tell your slicer to output "RepRap"
flavor.

## Choose a specific port and baud rate (AUTO doesn't work)

Choose the port (/dev/ttyACM0) and the baud rate (115200) from the dropdowns. If
a port doesn't show up in the list (only AUTO), make sure the printer is on and
connected to OctoPrint via USB and then refresh the web page. On my pi, my
printer shows up as /dev/ttyACM0.

## Fix your slicer's start g-code

Change this line: `G92 Z-5` to `G92 X0 Y0 Z-5 A0 B0`
Change this line: `M132 X Y Z A B` to `M132 X Y Z`

If your first G92 line has a different value for Z instead of -5, keep the Z
value you've got. For example, `G92 Z0` becomes `G92 X0 Y0 Z0 A0 B0`.

# The long version

If those five things got you up and running and that's all you wanted to know,
you should be good to go. If you're curious about what x3g is, why you have to
do those five things, read on.

<!-- more -->

## What the heck is x3g?

X3g is similar to a binary version of g-code, but it's not quite a one to one
mapping. X3g has a bunch of advantages over g-code such as: lower overhead on
the printer's microprocessor; actually designed as a protocol (rather than
accidentally like gcode); etc.

X3g is actually a version of an earlier protocol for RepRap printers called
s3g.

The main disadvantage of x3g is that most software these days is written to work
with g-code printers directly and x3g printers need translation software to
convert the g-code to x3g and emulate a g-code printer's weird responses.

For the following discussion, we're going to assume g-code in millimeters.
G-code can actually handle different units. However, in the world of 3D printing
we basically only use millimeters and in fact, GPX only handles millimeters.

## What is GPX?

GPX (maybe _G_code _P_rocessor for _X_3g) was written by WHPThomas
(wingcommander) to bridge between software written for newer RepRap printers and
MakerBot's printers. It converts g-code to x3g format and takes x3g protocol
responses and turns them into ASCII text responses that look kinda like Marlin
would produce (since there isn't really a g-code response protocol).

## Why does the machine type and slicer gcode flavor matter to GPX?

X3g values are expressed in number of steps. G-code is usally expressed in
millimeters. GPX has to know the steps per millimeter for your machine to do the
conversion.

Makerbot has produced several slicers over the years and there are a few
g-code's they put out that are different for every other printer out there. In
particular, M109 is set hotend temp and wait for it to be reached for RepRap,
but for MakerBot, it means set the heatbed temperature and don't wait. Also,
M106 and M107 for Reprap control the print cooling fan. MakerBot uses M126 and
M127 for that and M106/M107 control the extruder's heatsink fan.

Neither of those differences matter once you get to x3g, but what matters is
that GPX knows who/what generated your g-code. If you use any slicer besides
MakerBot or RepG, you should choose "RepRap" in both the slicer and GPX.

## Why is the start g-code wrong?

A lot of people have problems printing two files in a row using OctoPrint and
the GPX plugin. The reason it affects so many people is because the most common
start gcodes floating around out on the internet and in your favorite slicer,
make an assumption that isn't correct.

The G92 command in gcode and for most firmwares, sets the current position to a
specified value. For example, `G92 Z-5` means "set the absolute position of
where the hotend is now for the Z axis to -5mm", so that when I say `G1 Z0` in
absolute coordinates it'll move the Z axis 5 millimeters in the postive
direction. Also, and this is the important bit, it will leave all the other
coordinates alone.

Unfortunately, the x3g analog of G92 is opcode 140 and it doesn't allow you to
specify only some of the axes. It always takes all the axes. So GPX makes up
values for the other axes and sends those made up numbers along. When you're
converting a file to x3g with your slicer in "offline" mode, this will likely be
0 at the beginning. GPX has to keep track for later in the file so that things
like G92 E0 work properly.

And in particular, it's probably confusion over the absolute position of the
extruders that is causing the problem because after the `M132 X Y Z A B` all the
actual positions are known to the bot and after the next absolute move, will 
also be known to GPX. Problem is that in most cases, only one of the two
extruders is used and that other extruder floating out there makes GPX do weird
stuff to compensate for the axes it doesn't know.

This is why it is my advice to remove the A and B coordinate from the "Recall
home position" gcode `M132` because you most likely want them at 0 at the
beginning of a print anyway and using G92 to set them to 0 rather than recalling
a home position from the eeprom lets your gcode file, GPX and the bot to all
be on the same page.

## Why don't you fix it in the plugin since other host software seems to work

We could change things so that at the start of a print, it always stomps on the
current position with 0's to make it behave like the offline case. The problem
is that this could mess up scenarios that some people have working where they do
some manual set up before printing or break gcode into multiple files without
homing in between, etc.

I considered various ways to fix this automagically, but everything I came up
with has undesirable side effects in some circumstance or another. One
possibility would be to have a checkbox that when set means: the first G92 after
the start of a print that specifies less than all the axes, assume it meant zero
for the rest. Then folks who don't want to zero them out (a continuation file 
hand edited, for example) can clear it. Perhaps a later version of the plugin
will have such a checkbox.

