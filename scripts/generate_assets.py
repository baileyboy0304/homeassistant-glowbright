"""Generate original code-authored GlowBright brand assets and English strings."""

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "glowbright"
BRAND = ROOT / "brand"
BRAND.mkdir(exist_ok=True)
for size, suffix in ((256, ""), (512, "@2x")):
    scale = 4
    image = Image.new("RGBA", (size * scale, size * scale))
    draw = ImageDraw.Draw(image)
    def box(values):
        return tuple(int(v * size * scale / 256) for v in values)
    draw.rounded_rectangle(box((8, 8, 248, 248)), radius=int(size * scale * .25), fill="#123d50")
    draw.arc(box((49, 45, 211, 211)), 45, 315, fill="#4bd5be", width=int(size*scale*.045))
    draw.line([box((210, 128)), box((170,128))], fill="#4bd5be", width=int(size*scale*.045))
    draw.polygon([box(p) for p in ((141,48),(89,139),(122,139),(110,203),(169,111),(135,111))],fill="#ffcf61")
    image.resize((size,size),Image.Resampling.LANCZOS).save(BRAND / f"icon{suffix}.png")
logo = Image.new("RGBA", (1024,256))
logo.alpha_composite(Image.open(BRAND / "icon.png"),(0,0))
draw = ImageDraw.Draw(logo)
font=ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",110)
draw.text((280,61),"GlowBright",font=font,fill="#123d50")
logo.save(BRAND / "logo.png")
draw.rectangle((265,0,1024,256),fill=(0,0,0,0))
draw.text((280,61),"GlowBright",font=font,fill="#e8f7f5")
logo.save(BRAND / "dark_logo.png")

steps = {
    "user":{"title":"Connect your Bright account","description":"Use your existing Bright login. DCC data often arrives 24–48 hours late.","data":{"username":"Bright username or email","password":"Password"}},
    "electricity":{"title":"Choose electricity","description":"Every active electricity resource is listed independently, including resources in different Virtual Entities.","data":{"resource":"Electricity consumption resource"}},
    "gas":{"title":"Choose gas","description":"Gas may come from a different Virtual Entity. Select None for electricity only.","data":{"resource":"Gas consumption resource"}},
    "costs":{"title":"Historical cost resources","description":"Only cost streams in each selected meter's Virtual Entity are shown. If several exist, choose the corresponding stream. None keeps consumption enabled without costs.","data":{"electricity_cost":"Electricity historical cost","gas_cost":"Gas historical cost"}},
    "confirm":{"title":"Confirm meter selection","description":"Electricity: {electricity}\n\nGas: {gas}\n\nChanging a resource clears and rebuilds only that fuel's GlowBright history. Informational daily sensors are not the Energy source."},
}
errors={"invalid_auth":"Bright rejected the credentials. Check your username and password.","cannot_connect":"Unable to reach Glowmarkt. Please try again.","invalid_resource":"Choose a resource from the displayed list.","calorific_required":"Enter a calorific value to enable estimated gas conversion."}
aborts={"already_configured":"This Bright account is already configured.","wrong_account":"Use the same Bright account as the existing configuration.","no_resources":"No supported active electricity resources were found.","reauth_successful":"Bright authentication was updated.","reconfigure_successful":"GlowBright was reconfigured."}
options={"init":{"title":"GlowBright options","description":"A resource or gas conversion change rebuilds that fuel's history. Conversion is an estimate; use the calorific value from your bill.","data":{"backfill_days":"Historical backfill depth (days)","refresh_days":"Recent mutable window (days)","panel_enabled":"Show GlowBright sidebar panel","gas_conversion":"Convert gas m³ to estimated kWh","calorific_value":"Calorific value (MJ/m³)","volume_correction":"Volume correction factor"}},**{key:value for key,value in steps.items() if key!="user"}}
target=ROOT / "translations"
target.mkdir(exist_ok=True)
(target / "en.json").write_text(json.dumps({"config":{"step":steps,"error":errors,"abort":aborts},"options":{"step":options,"error":errors,"abort":aborts}},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
