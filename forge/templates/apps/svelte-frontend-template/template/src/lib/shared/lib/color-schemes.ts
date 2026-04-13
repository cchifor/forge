export interface ColorScheme {
	name: string;
	label: string;
	lightPrimary: string;
	darkPrimary: string;
	lightContainer: string;
	darkContainer: string;
}

export const colorSchemes: ColorScheme[] = [
	{
		name: 'blue',
		label: 'Blue',
		lightPrimary: '211 100% 50%',
		darkPrimary: '211 100% 68%',
		lightContainer: '211 100% 92%',
		darkContainer: '211 50% 20%'
	},
	{
		name: 'indigo',
		label: 'Indigo',
		lightPrimary: '231 48% 48%',
		darkPrimary: '231 68% 72%',
		lightContainer: '231 68% 92%',
		darkContainer: '231 38% 20%'
	},
	{
		name: 'hippieBlue',
		label: 'Hippie Blue',
		lightPrimary: '199 58% 44%',
		darkPrimary: '199 58% 68%',
		lightContainer: '199 58% 92%',
		darkContainer: '199 38% 20%'
	},
	{
		name: 'aquaBlue',
		label: 'Aqua Blue',
		lightPrimary: '193 82% 31%',
		darkPrimary: '193 72% 58%',
		lightContainer: '193 72% 92%',
		darkContainer: '193 52% 18%'
	},
	{
		name: 'brandBlue',
		label: 'Brand Blue',
		lightPrimary: '209 100% 44%',
		darkPrimary: '209 90% 68%',
		lightContainer: '209 90% 92%',
		darkContainer: '209 60% 20%'
	},
	{
		name: 'deepBlue',
		label: 'Deep Blue',
		lightPrimary: '224 64% 33%',
		darkPrimary: '224 64% 62%',
		lightContainer: '224 64% 92%',
		darkContainer: '224 44% 18%'
	},
	{
		name: 'sakura',
		label: 'Sakura',
		lightPrimary: '339 70% 48%',
		darkPrimary: '339 70% 72%',
		lightContainer: '339 70% 92%',
		darkContainer: '339 50% 20%'
	},
	{
		name: 'mandyRed',
		label: 'Mandy Red',
		lightPrimary: '0 58% 50%',
		darkPrimary: '0 58% 70%',
		lightContainer: '0 58% 92%',
		darkContainer: '0 38% 20%'
	},
	{
		name: 'red',
		label: 'Red',
		lightPrimary: '0 80% 44%',
		darkPrimary: '0 80% 68%',
		lightContainer: '0 80% 92%',
		darkContainer: '0 60% 18%'
	},
	{
		name: 'redWine',
		label: 'Red Wine',
		lightPrimary: '345 60% 30%',
		darkPrimary: '345 60% 60%',
		lightContainer: '345 60% 92%',
		darkContainer: '345 40% 18%'
	},
	{
		name: 'purpleBrown',
		label: 'Purple Brown',
		lightPrimary: '290 28% 36%',
		darkPrimary: '290 28% 62%',
		lightContainer: '290 28% 92%',
		darkContainer: '290 18% 18%'
	},
	{
		name: 'green',
		label: 'Green',
		lightPrimary: '150 60% 30%',
		darkPrimary: '150 60% 58%',
		lightContainer: '150 60% 92%',
		darkContainer: '150 40% 18%'
	},
	{
		name: 'money',
		label: 'Money',
		lightPrimary: '140 38% 36%',
		darkPrimary: '140 38% 60%',
		lightContainer: '140 38% 92%',
		darkContainer: '140 28% 18%'
	},
	{
		name: 'jungle',
		label: 'Jungle',
		lightPrimary: '160 50% 28%',
		darkPrimary: '160 50% 56%',
		lightContainer: '160 50% 92%',
		darkContainer: '160 30% 16%'
	},
	{
		name: 'greyLaw',
		label: 'Grey Law',
		lightPrimary: '210 14% 40%',
		darkPrimary: '210 14% 64%',
		lightContainer: '210 14% 92%',
		darkContainer: '210 10% 20%'
	},
	{
		name: 'wasabi',
		label: 'Wasabi',
		lightPrimary: '80 50% 38%',
		darkPrimary: '80 50% 62%',
		lightContainer: '80 50% 92%',
		darkContainer: '80 30% 18%'
	},
	{
		name: 'gold',
		label: 'Gold',
		lightPrimary: '42 78% 40%',
		darkPrimary: '42 78% 62%',
		lightContainer: '42 78% 92%',
		darkContainer: '42 58% 18%'
	},
	{
		name: 'mango',
		label: 'Mango',
		lightPrimary: '28 80% 48%',
		darkPrimary: '28 80% 66%',
		lightContainer: '28 80% 92%',
		darkContainer: '28 60% 18%'
	},
	{
		name: 'amber',
		label: 'Amber',
		lightPrimary: '36 100% 40%',
		darkPrimary: '36 100% 62%',
		lightContainer: '36 100% 92%',
		darkContainer: '36 70% 18%'
	},
	{
		name: 'vesuviusBurn',
		label: 'Vesuvius Burn',
		lightPrimary: '14 70% 36%',
		darkPrimary: '14 70% 60%',
		lightContainer: '14 70% 92%',
		darkContainer: '14 50% 18%'
	}
];

export function getSchemeByName(name: string): ColorScheme {
	return colorSchemes.find((s) => s.name === name) ?? colorSchemes[0];
}
