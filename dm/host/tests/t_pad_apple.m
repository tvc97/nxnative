// Face buttons of the shared GameController adapter (pad_apple.h) with fake pads: by position on most pads, by label on a Nintendo pad, by label on every pad with DM_PAD_FACE=label;
// no physical controller is needed.
#import "../pad_apple.h"
#include <assert.h>
#include <stdio.h>

@interface TestButton : NSObject
@property BOOL isPressed;
@end
@implementation TestButton
@end
@interface TestController : NSObject
@property NSString *productCategory;
@end
@implementation TestController
@end
@interface TestPad : NSObject
@property TestController *controller;
@property TestButton *buttonA, *buttonB, *buttonX, *buttonY;
@end
@implementation TestPad
@end

// The Switch buttons of a pad of this category with only the named GameController button pressed
static uint64_t face_as(NSString *category, char pressed, int label) {
    TestPad *g = [TestPad new]; g.controller = [TestController new]; g.controller.productCategory = category;
    g.buttonA = [TestButton new]; g.buttonB = [TestButton new]; g.buttonX = [TestButton new]; g.buttonY = [TestButton new];
    TestButton *b = pressed == 'A' ? g.buttonA : pressed == 'B' ? g.buttonB : pressed == 'X' ? g.buttonX : g.buttonY;
    b.isPressed = YES;
    return label < 0 ? dm_pad_face((GCExtendedGamepad *)(id)g) : dm_pad_face_as((GCExtendedGamepad *)(id)g, label);
}
static uint64_t face(NSString *category, char pressed) { return face_as(category, pressed, -1); }

int main(void) { @autoreleasepool {
    for (NSString *k in @[@"Xbox One", @"DualSense", @"HID"]) {   // by position: buttonA bottom (B), buttonB right (A), buttonX left (Y), buttonY top (X)
        assert(face(k, 'A') == DM_BTN_B); assert(face(k, 'B') == DM_BTN_A); assert(face(k, 'X') == DM_BTN_Y); assert(face(k, 'Y') == DM_BTN_X);
    }
    assert(face(nil, 'B') == DM_BTN_A);   // no category: by position
    for (NSString *k in @[@"Switch Pro Controller", @"Nintendo Switch Joy-Con (L/R)", @"Nintendo Switch Joy-Con (R)"]) {   // by label
        assert(face(k, 'A') == DM_BTN_A); assert(face(k, 'B') == DM_BTN_B); assert(face(k, 'X') == DM_BTN_X); assert(face(k, 'Y') == DM_BTN_Y);
    }
    for (NSString *k in @[@"Xbox One", @"DualSense", @"HID", @"Switch Pro Controller"]) {   // by label on every pad: the button marked A is A
        assert(face_as(k, 'A', 1) == DM_BTN_A); assert(face_as(k, 'B', 1) == DM_BTN_B); assert(face_as(k, 'X', 1) == DM_BTN_X); assert(face_as(k, 'Y', 1) == DM_BTN_Y);
    }
    setenv("DM_PAD_FACE", "label", 1); assert(dm_pad_face_by_label() && face(@"Xbox One", 'A') == DM_BTN_A);
    setenv("DM_PAD_FACE", "position", 1); assert(!dm_pad_face_by_label() && face(@"Xbox One", 'A') == DM_BTN_B);
    setenv("DM_PAD_FACE", "bogus", 1); assert(face(@"Xbox One", 'A') == DM_BTN_B);   // anything else: by position
    unsetenv("DM_PAD_FACE");
    TestPad *g = [TestPad new];   // nothing pressed, buttons nil: none
    assert(dm_pad_face((GCExtendedGamepad *)(id)g) == 0);
    printf("t_pad_apple OK\n");
} return 0; }
