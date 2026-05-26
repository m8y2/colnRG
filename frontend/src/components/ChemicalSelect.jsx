import AnimatedSelect from "./AnimatedSelect";
import { CHEMICALS } from "../utils";

export default function ChemicalSelect({ value, onChange }) {
  return (
    <AnimatedSelect
      options={CHEMICALS}
      value={value}
      onChange={onChange}
    />
  );
}
