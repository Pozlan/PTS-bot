"""
Word lists for /word. Plain 4-letter lowercase words only.

ANSWERS  = common words the bot can pick as the secret word.
EXTRA    = less common (but real) words that are accepted as guesses only,
           so a fair guess isn't rejected, but the secret is never obscure.

To add words, just add them to either string below -- anything that isn't
exactly 4 letters a-z is ignored automatically.
"""

_ANSWERS = """
able acid aged also area army away baby back ball band bank base bath bear beat been beer bell belt best
bike bill bird blow blue blur boat body bolt bomb bond bone book boom born boss both bowl bulk bump burn
bush busy buzz cafe cake call calm came camp card care case cash cast cell chat chef chin chip chop city
clap claw clay clip club coal coat code coin cold come cook cool cope copy core cost crab crew crop crow
curl dare dark dash data date dawn days dead deal dear debt deep deny dent desk dial dice diet dime dirt
dish disc dive dock does dome done door dose dove down draw drew drop drug drum dual duck dull dune dusk
dust duty each earn ease east easy edge else even ever evil exit face fact fail fair fall fame fang farm
fast fate fear feed feel feet fell felt fern file fill film find fine fire firm fish five flag flat flip
flow foam folk food foot fork form fort four free frog from fuel full fund gain game gate gave gaze gear
gene gift girl give glad glow glue goal goat goes gold golf gone good gown grab gray grew grid grin grip
grow gulf gust hair half hall hand hang hard harm hate have hawk head hear heat heap held hell help herb
here hero high hike hill hint hire hive hold hole holy home hook hope horn host hour howl huge hung hunt
hurt idea inch into iron item jade jail jazz jeep join joke jump jury just keen keep kept kick kill kind
king kite knee knew knot know lack lady laid lake lamp land lane last late lawn lazy lead leaf leap left
lend lens less life lift like lime limp line link lion list live load loan lock logo long look lord lose
loss lost love luck lump lung lure made mail main make male mall many mark mask mass maze meal mean meat
meet melt menu mere mild mile milk mind mine miss mist mode mood moon more moss most moth move much mule
must myth nail name navy near neck need nest news next nice nine none noon nose note noun okay once only
onto open oral oven over pace pack page paid pain pair pale palm park part pass past path pawn peak peel
pest pick pile pink pipe plan play plot plug plum plus poem poet pole poll pond pony pool poor port pose
post pour pray pull pump pure push quiz race rack raft rail rain rank rare rate read real rear reed rely
rent rest rice rich ride ring rink rise risk road robe rock role roll roof room root rope rose ruby ruin
rule rush rust sack safe sage said sail sake sale salt same sand save scan seal seat seed seek seem seen
self sell send sent shed ship shoe shop shot show shut sick side sign silk sing sink site size skin skip
slam slim slip slow snap snow soft soil sold sole some song soon sort soul soup spin spit spot spur star
stay stem step stir stop such suit sure swan swim tack tail take tale talk tall tank tape task team tear
tech tell tend tent term test text thaw than that them then they thin this thud thus tick tide tidy tied
till time tiny tire toad told toll tomb tone took tool torn tour town trap tree trim trip true tube tune
turn tusk twin type ugly unit upon urge used user vase vast veil vein very vibe vice view vine volt vote
wade wage wait wake walk wall want warm warn wash wasp wave ways weak wear weed week well went were west
what when whip whom wick wide wife wild will wind wine wing wink wipe wire wise wish with wolf wood word
wore work worm worn wrap yard yarn yeah year yell yoga yolk your zero zinc zone zoom
"""

_EXTRA = """
abut ache aide ally amid arch atom aunt axis bald bark barn bead beam bean beef bend bias bite blob blot
boil bold brew brim buck bull cage calf cape cart cave chew clue cone cord corn cozy cube cult cure dame
damp deck deed deer dine dope drag drip dude dumb echo edit epic envy exam fade fist flap flaw flea flee
flex flux fond fool fowl fray gale gasp germ glee gnat gram grim grit gulp gush hack halt haze heal hood
hoop hubs hull hush icon inks jolt keys kiss knit knob lace lash leak lean lick lint loft loom loop lore
lull lush mace meek mesh mica mink moat mock mold monk mute nape nerd newt nook numb oath odds omen onyx
pact pail pane pant pave peer pigs plea plod pods pork pout prey prop pulp punk quit rage raid ramp rash
rave reef rein rend ribs rind riot rump rune sash scab scar seam shin shun sift silo skew slab slap slit
slot slug smug snag snub soak soar sock sofa sore span spar spun stab stew stub suds sulk swap swat tact
tarp taut tray trio trot tuck twig vain vent vest vial void weld wits yawn zeal zing
"""


def _clean(blob: str) -> list[str]:
    seen: dict[str, None] = {}
    for w in blob.split():
        w = w.lower()
        if len(w) == 4 and w.isascii() and w.isalpha():
            seen[w] = None
    return list(seen)


ANSWERS: list[str] = _clean(_ANSWERS)
VALID: frozenset[str] = frozenset(ANSWERS) | frozenset(_clean(_EXTRA))
