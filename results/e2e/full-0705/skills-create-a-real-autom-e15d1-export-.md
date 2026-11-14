# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: skills.spec.ts >> create a real automation, run it on AC20, and display and export its persisted report
- Location: e2e/skills.spec.ts:43:1

# Error details

```
Test timeout of 60000ms exceeded.
```

```
Error: locator.selectOption: Test timeout of 60000ms exceeded.
Call log:
  - waiting for getByRole('region', { name: 'Automations', exact: true }).getByRole('form', { name: 'Create automation' }).getByLabel('Automation drawing', { exact: true })

```

# Page snapshot

```yaml
- generic [ref=e3]:
  - link "Skip to content" [ref=e4] [cursor=pointer]:
    - /url: "#main-content"
  - complementary "Workspace sidebar" [ref=e5]:
    - link "Hologram home" [ref=e6] [cursor=pointer]:
      - /url: "#/overview"
      - text: Hologram
    - generic [ref=e7]:
      - generic [aria-hidden] [ref=e8]: D
      - generic [ref=e9]: Project
      - combobox "Project" [ref=e10] [cursor=pointer]:
        - option "Construction project" [selected]
    - navigation "Workspace navigation" [ref=e11]:
      - link "Overview" [ref=e13] [cursor=pointer]:
        - /url: "#/overview"
      - link "Chat" [ref=e18] [cursor=pointer]:
        - /url: "#/chat"
      - link "Accuracy" [ref=e23] [cursor=pointer]:
        - /url: "#/accuracy"
      - link "Changes" [ref=e30] [cursor=pointer]:
        - /url: "#/changes"
      - link "Skills" [ref=e35] [cursor=pointer]:
        - /url: "#/skills"
      - link "Data" [ref=e39] [cursor=pointer]:
        - /url: "#/data"
      - link "Automations" [ref=e45] [cursor=pointer]:
        - /url: "#/automations"
      - link "More" [ref=e49] [cursor=pointer]:
        - /url: "#/accuracy"
    - generic [aria-hidden] [ref=e55]: AK
  - main [ref=e56]:
    - generic: Connected workspace
    - heading "Automations" [level=1] [ref=e59]
    - region "Automations" [ref=e60]:
      - generic [ref=e61]:
        - generic [ref=e62]:
          - heading "Automations" [level=2] [ref=e63]
          - paragraph [ref=e67]: Run a saved question on a schedule and keep its latest report.
        - button "Refresh" [ref=e68] [cursor=pointer]
      - form "Create automation" [ref=e69]:
        - heading "Create an automation" [level=3] [ref=e70]
        - generic [ref=e71]:
          - text: Automation name
          - textbox "Automation name" [ref=e72]:
            - /placeholder: Window report
            - text: AC20 daily 1794631003430
        - generic [ref=e73]:
          - text: Automation prompt
          - textbox "Automation prompt" [active] [ref=e74]:
            - /placeholder: How many windows are there?
            - text: How many windows are there?
        - generic [ref=e75]:
          - generic [ref=e76]:
            - text: Automation drawing
            - combobox "Automation drawing" [ref=e77]:
              - option "Choose a drawing" [disabled]
              - option "colorful-11397" [selected]
              - option "colorful-11400"
              - option "colorful-11960"
              - option "colorful-12200"
              - option "colorful-13685"
              - option "colorful-1732"
              - option "colorful-2002"
              - option "colorful-2194"
              - option "colorful-34"
              - option "colorful-6327"
              - option "colorful-7513"
              - option "colorful-8389"
              - option "colorful-8759"
              - option "high_quality-10306"
              - option "high_quality-10785"
              - option "high_quality-108"
              - option "high_quality-1097"
              - option "high_quality-11377"
              - option "high_quality-11384"
              - option "high_quality-11459"
              - option "high_quality-11553"
              - option "high_quality-1212"
              - option "high_quality-12126"
              - option "high_quality-12235"
              - option "high_quality-12239"
              - option "high_quality-12761"
              - option "high_quality-13029"
              - option "high_quality-13107"
              - option "high_quality-13137"
              - option "high_quality-1391"
              - option "high_quality-1500"
              - option "high_quality-1506"
              - option "high_quality-1647"
              - option "high_quality-1655"
              - option "high_quality-20147"
              - option "high_quality-3086"
              - option "high_quality-3692"
              - option "high_quality-5080"
              - option "high_quality-5682"
              - option "high_quality-5815"
              - option "high_quality-6565"
              - option "high_quality-6732"
              - option "high_quality-698"
              - option "high_quality-729"
              - option "high_quality-7768"
              - option "high_quality-7932"
              - option "high_quality-8026"
              - option "high_quality-8033"
              - option "high_quality-8177"
              - option "high_quality-8488"
              - option "high_quality-8530"
              - option "high_quality-8781"
              - option "high_quality-9770"
              - option "high_quality-9775"
              - option "high_quality_architectural-1000"
              - option "high_quality_architectural-10000"
              - option "high_quality_architectural-10026"
              - option "high_quality_architectural-10096"
              - option "high_quality_architectural-10142"
              - option "high_quality_architectural-10161"
              - option "high_quality_architectural-10196"
              - option "high_quality_architectural-10254"
              - option "high_quality_architectural-10290"
              - option "high_quality_architectural-10321"
              - option "high_quality_architectural-10368"
              - option "high_quality_architectural-10370"
              - option "high_quality_architectural-10491"
              - option "high_quality_architectural-10498"
              - option "high_quality_architectural-10545"
              - option "high_quality_architectural-10571"
              - option "high_quality_architectural-10581"
              - option "high_quality_architectural-11007"
              - option "high_quality_architectural-11011"
              - option "high_quality_architectural-11012"
              - option "high_quality_architectural-11059"
              - option "high_quality_architectural-11142"
              - option "high_quality_architectural-11169"
              - option "high_quality_architectural-11257"
              - option "high_quality_architectural-11280"
              - option "high_quality_architectural-11319"
              - option "high_quality_architectural-11426"
              - option "high_quality_architectural-11465"
              - option "high_quality_architectural-1153"
              - option "high_quality_architectural-11566"
              - option "high_quality_architectural-11572"
              - option "high_quality_architectural-11602"
              - option "high_quality_architectural-1169"
              - option "high_quality_architectural-11769"
              - option "high_quality_architectural-11786"
              - option "high_quality_architectural-11826"
              - option "high_quality_architectural-11866"
              - option "high_quality_architectural-11877"
              - option "high_quality_architectural-11926"
              - option "high_quality_architectural-11975"
              - option "high_quality_architectural-12027"
              - option "high_quality_architectural-12077"
              - option "high_quality_architectural-12085"
              - option "high_quality_architectural-12166"
              - option "high_quality_architectural-12188"
              - option "high_quality_architectural-12232"
              - option "high_quality_architectural-12245"
              - option "high_quality_architectural-1241"
              - option "high_quality_architectural-12415"
              - option "high_quality_architectural-12454"
              - option "high_quality_architectural-12617"
              - option "high_quality_architectural-12684"
              - option "high_quality_architectural-12688"
              - option "high_quality_architectural-12698"
              - option "high_quality_architectural-12864"
              - option "high_quality_architectural-12943"
              - option "high_quality_architectural-13040"
              - option "high_quality_architectural-13048"
              - option "high_quality_architectural-13075"
              - option "high_quality_architectural-13161"
              - option "high_quality_architectural-13210"
              - option "high_quality_architectural-13309"
              - option "high_quality_architectural-13326"
              - option "high_quality_architectural-13388"
              - option "high_quality_architectural-1357"
              - option "high_quality_architectural-13607"
              - option "high_quality_architectural-1368"
              - option "high_quality_architectural-13767"
              - option "high_quality_architectural-13794"
              - option "high_quality_architectural-13843"
              - option "high_quality_architectural-1402"
              - option "high_quality_architectural-14155"
              - option "high_quality_architectural-14339"
              - option "high_quality_architectural-14341"
              - option "high_quality_architectural-14441"
              - option "high_quality_architectural-14494"
              - option "high_quality_architectural-145"
              - option "high_quality_architectural-14533"
              - option "high_quality_architectural-14566"
              - option "high_quality_architectural-14612"
              - option "high_quality_architectural-14759"
              - option "high_quality_architectural-14762"
              - option "high_quality_architectural-14809"
              - option "high_quality_architectural-14812"
              - option "high_quality_architectural-1524"
              - option "high_quality_architectural-16"
              - option "high_quality_architectural-1706"
              - option "high_quality_architectural-1772"
              - option "high_quality_architectural-1778"
              - option "high_quality_architectural-18"
              - option "high_quality_architectural-1814"
              - option "high_quality_architectural-1838"
              - option "high_quality_architectural-1886"
              - option "high_quality_architectural-1903"
              - option "high_quality_architectural-1933"
              - option "high_quality_architectural-1967"
              - option "high_quality_architectural-20071"
              - option "high_quality_architectural-20093"
              - option "high_quality_architectural-2014"
              - option "high_quality_architectural-2100"
              - option "high_quality_architectural-2105"
              - option "high_quality_architectural-2145"
              - option "high_quality_architectural-2164"
              - option "high_quality_architectural-247"
              - option "high_quality_architectural-2512"
              - option "high_quality_architectural-2530"
              - option "high_quality_architectural-2580"
              - option "high_quality_architectural-2609"
              - option "high_quality_architectural-3660"
              - option "high_quality_architectural-3710"
              - option "high_quality_architectural-381"
              - option "high_quality_architectural-3819"
              - option "high_quality_architectural-3915"
              - option "high_quality_architectural-3919"
              - option "high_quality_architectural-392"
              - option "high_quality_architectural-4064"
              - option "high_quality_architectural-4068"
              - option "high_quality_architectural-41"
              - option "high_quality_architectural-4517"
              - option "high_quality_architectural-4561"
              - option "high_quality_architectural-4609"
              - option "high_quality_architectural-4685"
              - option "high_quality_architectural-4711"
              - option "high_quality_architectural-4845"
              - option "high_quality_architectural-4855"
              - option "high_quality_architectural-4897"
              - option "high_quality_architectural-4914"
              - option "high_quality_architectural-5006"
              - option "high_quality_architectural-5028"
              - option "high_quality_architectural-504"
              - option "high_quality_architectural-5602"
              - option "high_quality_architectural-5640"
              - option "high_quality_architectural-5742"
              - option "high_quality_architectural-5788"
              - option "high_quality_architectural-5906"
              - option "high_quality_architectural-594"
              - option "high_quality_architectural-6001"
              - option "high_quality_architectural-6037"
              - option "high_quality_architectural-6051"
              - option "high_quality_architectural-6081"
              - option "high_quality_architectural-6212"
              - option "high_quality_architectural-6299"
              - option "high_quality_architectural-6352"
              - option "high_quality_architectural-6355"
              - option "high_quality_architectural-6369"
              - option "high_quality_architectural-6387"
              - option "high_quality_architectural-6402"
              - option "high_quality_architectural-6405"
              - option "high_quality_architectural-6467"
              - option "high_quality_architectural-6581"
              - option "high_quality_architectural-6642"
              - option "high_quality_architectural-672"
              - option "high_quality_architectural-7041"
              - option "high_quality_architectural-7098"
              - option "high_quality_architectural-745"
              - option "high_quality_architectural-7549"
              - option "high_quality_architectural-7567"
              - option "high_quality_architectural-7598"
              - option "high_quality_architectural-7607"
              - option "high_quality_architectural-7688"
              - option "high_quality_architectural-7731"
              - option "high_quality_architectural-7787"
              - option "high_quality_architectural-7838"
              - option "high_quality_architectural-7858"
              - option "high_quality_architectural-7894"
              - option "high_quality_architectural-7924"
              - option "high_quality_architectural-8022"
              - option "high_quality_architectural-8029"
              - option "high_quality_architectural-8321"
              - option "high_quality_architectural-8394"
              - option "high_quality_architectural-8604"
              - option "high_quality_architectural-8638"
              - option "high_quality_architectural-8639"
              - option "high_quality_architectural-8705"
              - option "high_quality_architectural-8737"
              - option "high_quality_architectural-8755"
              - option "high_quality_architectural-9135"
              - option "high_quality_architectural-9173"
              - option "high_quality_architectural-9198"
              - option "high_quality_architectural-9386"
              - option "high_quality_architectural-9405"
              - option "high_quality_architectural-9460"
              - option "high_quality_architectural-9488"
              - option "high_quality_architectural-9661"
              - option "high_quality_architectural-9680"
              - option "high_quality_architectural-9787"
              - option "high_quality_architectural-9833"
              - option "Altaar met voorstelling van Annunciatie, ionische zuilen en grondplan"
              - option "Arhitektonski crtež"
              - option "Arkitekttegning av hus"
              - option "Bauzeichnung"
              - option "Bouwtekening van Nic.Molenaar"
              - 'option "Cadre avec dessins de coupe transversale #0932"'
              - 'option "Chodorow : Querschnitt"'
              - option "Church of Madonna degli Angeli - Prospectus and side section"
              - option "Crkva Sv. Blaža, stubište/ulaz na prodekaonicu/tlocrt i presjek"
              - option "Dokument. Piirsalu 2-kl. külakooli ehitamisega seotud kirjavahetus. Koolimaja plaan - korruste plaan ja ristlõige. 1908-1916."
              - option "Elevation and cross-section of Normandie salt works and used instruments. Etching by Bénard after Goussier."
              - option "Elevation of St Jacobs Hospital and former Walloon Church at Schiedam"
              - option "[Estudo arquitectónico com alçado de igreja, planta da escadaria e colunas do pórtico]"
              - option "Floor Plan with Arrangement of Iconographic Programme, Holy Metropolitan Church of Amfissa"
              - option "garden table with fountain"
              - option "Grabmal Adolf Loos I, Wien XI., Zentralfriedhof, Sektor 32c der Ehrengräber, Skizze"
              - option "\"Grundriss der vergleichenden Anatomie\", Gegenbaur, 1874"
              - option "Grundriss des Parterre, des ersten und zweiten Stockes, und des Dachbodens des Josephinums"
              - option "Hall, Rathaus, hölzerne Balkendecke und -säule, Perspektive, Grundriss, Schnitt"
              - option "Interior of St. John’s Archcathedral Church in Warsaw on the 85th anniversary of the elevation of the temple to the dignity of the metropolitan church and the 19th exercise of the diecesis of J. E. Archbishop Fr. Wincentego Teofila Chościak-Popiela)"
              - option "Kaplicy Protestanck ZR 1614 w Gojcieniszkach. Rzut pociomy"
              - 'option "Käsikirjaline noodikogu: Saint-Saens - Élévation ou communion"'
              - option "Kosciol Pobernardynski w budskawiu pod wezwaniem Sw. Panny Marji. Elewacja boczna"
              - option "Kosciol Pobernardynski w budskawiu pod wezwaniem Sw. Panny Marji. Przekroj poziomy fundamentow fundamentow"
              - option "Lärbok i geometrisk ritning 1908"
              - 'option "Observatoire royal : élévation sur le jardin (titre forgé)"'
              - 'option "Observatoire royal : plan du rez-de-chaussée du côté de l’entrée (titre forgé)"'
              - 'option "[Palais exhibited in Warsaw behind the Wolski horns at No. 3084]: The ground floor plan"'
              - option "Part of the Ellis group of daguerreotypes."
              - option "Perfil y alzado cortado en los planes por la línea C, D ; Ydem por la línea A, B"
              - option "Plan et elevation d'une porte cochere"
              - option "Plano de la planta principal del palacio barcelonés llamado de la Virreina, en la Rambla"
              - 'option "[Planta de fortificação rectangular com quatro baluartes circulares e várias dependências]: [estudo de aula de fortificação]"'
              - option "[Planta de la Casa de Huérfanos de Lima]"
              - option "Plattegrond en gevel aan de tuinzijde van de Gilde der Ambachten"
              - option "Plattegrond met situatieschets van het huis van W. Claassen, het steegje Achter de Vergulde Truffel en een graanpakhuis. Hoort bij een klacht van Jacobus Brouwers tegen de ligging van een privaat tegen zijn graanpakhuis"
              - option "Plattegrond. Verzoek van Henri Jean Driessen, touwslager, om het gedeelte van de vroegere vestingwal gelegen tussen het laboratorium van de boterfabriek en de Kasterensmolen te gebruiken als lijnbaan."
              - option "Polska ludność rodzima Ziem Zachodnich i Północnych na łamach \"Przekroju\" w latach 1945-1949"
              - option "Primera planta de ensamblaje fotovoltáica"
              - option "Project for an Ashtray III (cup and elevation)"
              - option "Projekt, Pärnus, J.Pull'i hoone plaan, 1930"
              - option "Projet d'un autel dédié à Notre-Dame, élévation face/profil"
              - 'option "Proyecto de iglesia para Sayago : Sección longitudinal, sección por A.B., sección transversal : Montevideo Marzo de 1909"'
              - 'option "Puente sobre el rio Tiétar [ [Material cartográfico] ]: [Alzado General, Tejeda a Almaraz, Trozo 1º : Plano del proyecto de las obras de mejora del abastecimiento de aguas de Plasencia] /"'
              - option "Révhelyi Elemér képei"
              - option "Rissbildung an dem Schornstein 1 [m. Fertigstellungsangaben u. Lageplan]"
              - option "Ritning"
              - option "Ritning på väv över Nordiska museets huvudbyggnad. Absiden. Ritning till balkongräcke samt trappräcke i andra galleriet. Fast inredning och elevation(?). Trappräcke och balkongräcke. 47,5x67,5 cm. Tusch och rött. I Gust Clason 19 maj 1905."
              - option "Section of the brain"
              - option "[Spaccato interno e pianta di tempio romano]"
              - 'option "Stadttheater (auch: Grillo-Theater), Essen: Grundriss und Längsschnitt"'
              - option "Stambena i trgovačka zgrada za eksploataciju drva, tlocrt/mezanin"
              - 'option "St Helen''s Free School, Paddington, London: the elevation, above, and the plan, below, with a scale. Wood engraving, 1851, after T. Meyer."'
              - 'option "Technical drawing: Project for the new construction of a rye mill, 300 centers in 24 hours for Mr. W. Kolmann in Cesarka near Stryków"'
              - 'option "Technische Zeichnung : Dispositions-Grundriss für Herrn Mühlenbesitzer Wender in Mühlhausen, Thüringen"'
              - option "Udvari homlokzat"
              - option "Vila Vrbanić, pročelje/zapadno pročelje"
              - 'option "Vilkaviškio rajono, Stanaičių kaimo kapinyno situacijos plano brėžinys. Mastelis: 1:20000"'
              - option "Wien I, Bösendorferstraße 13, Palais Lützow, Eckrustika des 1. Stockes, Aufriß und Profil"
              - option "Άποψη και κάτοψη των Προπυλαίων του Παρθενώνα (φανταστική αναπαράσταση)."
              - option "Όψη και τομή του Ναού του Πορτούνου στην Όστια, ο οποίος μετατράπηκε σε χριστιανικό ναό."
              - option "1235 verkko-osaston piirustukset, Työväen asunnot Kirstin kadun varrella (1949)"
              - option "685 Vesijohtotarvikkeet, ventiilit ja hanat, Ritning till en 4\" afstängninsventil för Helsinfors vattenledning Pl.2. Plan Genomskärning 1:1 (1885)"
              - option "Alue 10, Träsk (suo), pohjapiirros"
              - option "Alue 60b Nygård, julkisivupiirustus"
              - option "Alue 60c Valo, asemapiirros"
              - option "Asunto-osakeyhtiö Brändö Domus, Kulosaarentie 4-8, asema- ja pohjapiirros (1967)"
              - option "Asunto-osakeyhtiö Brändö Domus, Kulosaarentie 4-8, asemapiirros (1968)"
              - option "Asunto-osakeyhtiö Brändö Domus, Kulosaarentie 4-8, julkisivupiirustus (1960)"
              - option "Asunto-osakeyhtiö Brändö Domus, Kulosaarentie 4-8, pohjapiirros (1968)"
              - option "Babcock Wilcox Ångpannor, sammanställningsritning (1916)"
              - option "Bengtsår, keittiörakennus, RN:o 10 (1945)"
              - option "Bengtsår, muonamiehen asunto (1938)"
              - option "Biegeplan. Fernheizdampfleitung (Mannefmann) (1960)"
              - option "Bröder Åström AB, Uleåborg, växthus"
              - option "Dir. Borg, Tammerfors, växthusb, leikkauspiirustus"
              - option "Disponentbostad För Herr Ingenjör Harry Zilliacus (1907)"
              - option "Eerikinkatu 31 (1979)"
              - 'option "Eskiss till verkstads- och lagerbygnad afsedd att uppföras å den Gasverket tillhörande delen af kvarteret no:179 i Helsinginfors stad: fasad mot Runebergsgatan (1913)"'
              - 'option "Eskiss till verkstads- och lagerbygnad afsedd att uppföras å den Gasverket tillhörande delen af kvarteret no:179 i Helsinginfors stad: skärning i A-B (1913)"'
              - option "Fabianinkatu 6, pohjapiirros (1905)"
              - option "Fridhäll-Ukkokoti, leikkauspiirustus"
              - option "Hammarskjöldintie 1, kaupungin puutarha-alue, julkisivupiirustus"
              - option "Hammarskjöldintie 1, kaupungin puutarha-alue, leikkauspiirustus"
              - option "Helsingfors Societetshus_nykyinen kaupungintalo_74_I_7_00002"
              - option "Hirsihuvila S. Wuorio, Helsinki, tuvan ovi ja lastenhuoneen ikkunaluukku, ajoittamaton"
              - 'option "Hotelli Rosendahl (Pyynikintie 13, Tampere), laajennus: asemapiirustus"'
              - option "Humallahden Uimalaitos, asemapiirros"
              - option "J. Tallbergin Kauppakuja, Kaivokatu 8 - Hakasalmenkatu 4, Helsinki, vaihtoehto, leikkauspiirustus A-B ja C-D, 1908"
              - option "Käärmetalo, huoltorakennus, pohjapiirustus, 0.kerros, lastenseimi, pesula, 3 asuntoa, Helsinki, 1.7.1949"
              - option "Käärmetalo, huoltorakennus, uimahalli, leikkauspiirustus B-B, Helsinki, 13.6.1950"
              - option "Käärmetalo, lamelli B, julkisivupiirustukset, kellarikerroksen ja 1.-4.kerroksen pohjapiirustukset, Helsinki, 18.5.1949"
              - option "Käärmetalo, rakennukset 1 ja 3, porrashuoneen kattoikkuna, detaljipiirustus, ajoittamaton"
              - option "Käärmetalo, rakennus 3, pohjapiirustus, 2.-4.kerros, Helsinki, 1.7.1949"
              - option "Kalevankatu 61, asemapiirros (1904)"
              - option "Kauppatori, Kioski, julkisivu- ja pohjapiirustus (1915)"
              - option "Korkeasaari_työpajarakennus_Julkisivut_koiliseen_ja_luoteeseen_1.50_27.10.1941_korj._24.3.1942"
              - option "Korkeavuorenkatu 29, asema- ja pohjapiirros (1884)"
              - option "Kouvolan kirkko, alttaritaulu"
              - option "Kouvolan kirkko, asemapiirustus, vaihtoehtoja"
              - option "Kouvolan kirkko, asemapiirustus, vaihtoehtoja"
              - option "Kouvolan kirkko, julkisivuluonnoksia"
              - option "Kouvolan kirkko, kalkki"
              - option "Kouvolan kirkko, kynttilänjalka ja viinipikari"
              - option "Kouvolan kirkko, pohja, kalustusvaihtoehtoja"
              - option "Kouvolan kirkko, sisäseinä"
              - option "Kouvolan kirkko, virsinumerot"
              - option "Laivasillankatu 14, julkisivu- ja leikkauspiirustus (1921)"
              - option "Lapinlahdenkadun kansakoulun asemapiirros (1959)"
              - option "Lapinlahdenkadun kansakoulun kellarikerros (1960)"
              - option "Lilla Olofsborg, kutsukilpailuehdotus, Kauppiaankatu 5, Katajanokka, Helsinki, 4.kerroksen pohjapiirustus, ajoittamaton"
              - option "Lilla Olofsborg, kutsukilpailuehdotus, Kauppiaankatu 5, Katajanokka, Helsinki, pohjapiirrosluonnos, huhtikuu 1902"
              - option "Mannerheimintie 17, Alue 49, Toivo, asemapiirros"
              - option "Mannerheimintie 17, Alue 49, Toivo, leikkauspiirustus"
              - option "Mannerheimintie 17, Alue 49, Toivo, leikkauspiirustus"
              - option "Meilahden Huvila-alue, 12 Ljungamo, julkisivu-, leikkaus-, pohja- ja asemapiirustus"
              - option "Meilahden Huvila-alue, 1 Bjälbo, asemapiirros"
              - option "Meilahden Huvila-alue, 21 Bredablick, asemapiirros"
              - option "Mittel partiet af ändfasaderna till Vattengasverket (1941)"
              - option "Nikkilän sairaala, rakennus 48, asuinrakennus (1968)"
              - option "Nya apparathuset i Sörnäs (1941)"
              - option "Olympiastadion, katsomon puurakenne, leikkauspiirustus, ei lopullinen version, Helsinki, 14.3.1950"
              - option "Olympiastadion, olympialiekin sijoitusehdotus, olympialiekki tuloskuulutustaulun katolla, Helsinki, 3.1.1952"
              - option "Olympiastadion, presidentin aition tuolit, Helsinki, 1937"
              - option "Olympiastadion, tajoiluhuoneen kalusteet, Helsinki, ajoittamaton"
              - 'option "Oy Paragon Ab toimitalo (Mäkelänkatu 84), sisustus: kalustemallit ja lukumäärät"'
              - option "Pääpiirustuksia kansakouluun, Väinölänkatu 7_10"
              - option "Pallokenttä, eri rakennuksien piirustuksia (1987)"
              - option "Pohjoisesplanadi 2, Ruotsalainen teatteri, pohjapiirros (1915)"
              - option "Portinvartijan huone, julkisivut (1965)"
              - option "Portinvartijan huone, leikkaus C-C (1965)"
              - option "Portinvartijan huone, vaakaleikkaus, seinätolppien mitat (1965)"
              - option "Rahatoimisto_135_I_21"
              - option "Riihimäen urheilupuisto, uimalaitos, leikkauspiirustus B-B, Riihimäki, 21.4.1951"
              - option "Rikhardinkadun kirjasto_Leikkaus_A-A_1.100_5.4.1949"
              - 'option "Ritning för tillbygnad av vakststuga å Gasverkets tomt no:252 i tionde stadsdelen av Helsingfors stad: fasad mot Svalbogatan (1941)"'
              - 'option "Ritning till apparathus qtt uppföras å Gasverkets tomt no:9 vid Svalbogatan i kvarteret no:252 av Helsingfors stad: fasad mot väster, fasad mot öster, första våningen"'
              - option "Ritning till pannhus afsedd att uppföras på för Gasverket reserverade delen af Fabriks-kvarteret no:252 af Helsinginfors stad (1909)"
              - 'option "Ritning till reningshus att uppföras å Gasverkets tomt no:9 vid Svalbogatan i kvarteret no:252 av Helsinginfors stad: fasad mot söder, fasad mot öster (1941)"'
              - 'option "Roihuvuoren vesitorni: julkisivuluonnos, \"Poimulehti\""'
              - 'option "Runosmäen lastentalo (Munterinpolku 2, Runosmäki, Turku): lounais- ja koillisjulkisivu"'
              - option "Sörnäisten panimoalue, julkisivupiirustus"
              - option "Suvilahden höyryvoimalaitos, hiilenmurskaamo, asemapiirros (1960)"
              - option "Suvilahden höyryvoimalaitos, hiilenmurskaamo, julkisivu ja pohjat_2 (1960)"
              - option "Suvilahden voimalaitos, liikemerkki, asemapiirros_2 (1969)"
              - option "Suvilahden voimalaitos, liikemerkki, sijoitus julkisivulle (1969)"
              - option "Suvilahden voimalaitos, liikemerkki, sijoitus julkisivulle_2 (1969)"
              - option "Tilkka Litt. A, julkisivupiirustus"
              - option "Tilkka Litt. A, leikkauspiirustus"
              - 'option "Till bygnad för Gasverkets mätarehus å tomt no:9 vid Svalbogatan i kvarteret no:252 av Helsingfors stad: källarvåningen, första våningen (1930)"'
              - 'option "Tillbygnad för Gasverkets mätarehus å tomt no:9 vid Svalbogatan i kvarteret no: av Helsingfors stad: fasad mot norr, fasad mot väster, fasad mo söder, situationplan (1930)"'
              - 'option "Tillbygnad för Gasverkets mätarehus å tomt no:9 vid Svalbogatan i kvarteret no: av Helsingfors stad: fasad mot norr, fasad mot väster, fasad mo söder, situationplan (1930)"'
              - option "Urheilukatu,alue 51, Kaavi, asemapiirros"
              - option "Vanha kelkkamäki 6, pohjapiirros (1948)"
              - option "Vanha kelkkamäki 9, julkisivupiirustus (1947)"
              - 'option "Villa Ljungberga, puutarhasuunnitelma: kiviterassi"'
              - option "Vuorimiehenkatu 4, asema- ja pohjapiirros (1905)"
              - option "2012 As-Built Site Plan Location - Utica Square, 21st and Utica Avenue, Tulsa, Tulsa County, OK"
              - option "2012 As-Built Site Plan - Utica Square, 21st and Utica Avenue, Tulsa, Tulsa County, OK"
              - option "Administration Building Sections - Statue of Liberty, Administration Building, Liberty Island, Manhattan, New York, New York County, NY"
              - option "Annex Floor Plan - Westside School, Annex, Corner of Washington Avenue and D Street, Las Vegas, Clark County, NV"
              - option "Arneson River Theater Section - San Antonio River Walk, 418 Villita Street, San Antonio, Bexar County, TX"
              - option "Basement Floor Plan - Conrad and Nellie Warren Residence, Highway 10, Deer Lodge, Powell County, MT"
              - option "Basement Floor Plan - First Methodist Episcopal Church , 129-133 Northwest Fourth Street, Oklahoma City, Oklahoma County, OK"
              - option "Bethlehem Steel Company, Site Plan 1923 - Cambria Iron Company, East side of Conemaugh River, Johnstown, Cambria County, PA"
              - option "Camp Curry, 400s Comfort Station Plan and Elevations - Camp Curry, 400s Comfort Station, Curry Village, Mariposa County, CA"
              - option "Camp Curry, Registration Office First Floor Plan - Camp Curry, Registration Office (Lounge, Post Office, Amphitheater Stage), Curry Village, Mariposa County, CA"
              - option "Cover Sheet, Site Plan, Newel Post, and Column Base - Poplar Grove National Cemetery, Rostrum, 8005 Vaughan Road, Petersburg, Petersburg, VA"
              - option "Cover Sheet, Site Plan, Newel Post, and Railing Post - Richmond National Cemetery, Rostrum, 1701 Williamsburg Road, Montrose, Henrico County, VA"
              - option "COVER SHEET WITH LOCATION MAP. - Bank of the United States, 80 Broad Street, Charleston, Charleston County, SC"
              - option "Cross Section Looking East - Eli Whitney Armory, Barn, Whitney Avenue, Hamden, New Haven County, CT"
              - option "Cross sections - Nims Ford Dealership, 116 North Main Street, Ekalaka, Carter County, MT"
              - option "Detail A,B, C, D, E, F - Griggs County Bridge, Spanning Sheyenne River at Route 2, Cooperstown, Griggs County, ND"
              - option "Details - Cedar City Automotive Repair Shop, Utility Building \"B\", 820 North Main Street, Cedar City, Iron County, UT"
              - option "Details - Kaiser Center, 300 Lakeside Drive, Oakland, Alameda County, CA"
              - option "Details - La Bajada Community Ditch and Mutual Domestic Water Association, Acequia, La Bajada, Santa Fe County, NM"
              - option "Details - Sulphite Railroad Bridge, Former Boston and Maine Railroad (originally Tilton and Franklin Railroad) spanning Winnipesautee River, Franklin, Merrimack County, NH"
              - option "DRIVE TERMINAL SECTION - Mad River Glen, Single Chair Ski Lift, 62 Mad River Glen Resort Road, Fayston, Washington County, VT"
              - option "East and south elevations, plan - San Jacinto Ranch, Generator House, San Jacinto, Elko County, NV"
              - option "East Elevation and Isometric of Roof Truss - Tibbals-Sager Cabin, South Pass Avenue, South Pass City, Fremont County, WY"
              - option "Elevations and Plan - Fort Laramie, N.C.O. Quarters, Fort Laramie, Goshen County, WY"
              - option "Elevations, Floor Plan, and Kitchen Linoleum - John Moulton Homestead, Bunkhouse, Approximately 60 feet southwest of house, Kelly, Teton County, WY"
              - option "Engine North Elevation, North East Elevation - Estate Rust-Op-Twist, Steam Engine and Cane Mill, Christiansted, St. Croix, VI"
              - option "Existing Planting Plan - Capitol Park, 900 East Oklahoma Avenue, Guthrie, Logan County, OK"
              - option "Exploded Panel Detail; Assembled Panel - Brown Bridge, Spanning Cold River, Upper Cold River Road, Shrewsbury, Rutland County, VT"
              - option "First and Second Floor Plans - Idaho House, South Pass Avenue, South Pass City, Fremont County, WY"
              - option "First Dwelling House and Lumber and Grist Mill Sections - North Family, Mount Lebanon Shaker Village, 202 Shaker Road, New Lebanon, Columbia County, NY"
              - option "First Floor and Second Floor Plans - John Moulton Homestead, Barn, Approximately 135 feet northeast of house, Kelly, Teton County, WY"
              - option "First Floor Plan - Grant-Kohrs Ranch, Ranch House, Highway 10, Deer Lodge, Powell County, MT"
              - option "First Floor Plan - Luna Lodge, 9119 Central Avenue Northeast, Albuquerque, Bernalillo County, NM"
              - option "First Floor Plan - Phoenix Mill, North bank of Still River, Phoenixville, Windham County, CT"
              - option "First Floor Plan - Shelburne Farms, Breeding Barn, 1611 Harbor Road, Shelburne, Chittenden County, VT"
              - option "First floor plan - Tavern-Store-Kitchen, Route 29 and Route 631, Madison, Madison County, VA"
              - option "Floor Plan - Level 3 Ore Bins - Belmont Mill, Approximately 7 miles south of U.S. Route 50 on USDA Forest Service Road No. 623, Ely, White Pine County, NV"
              - option "Floor Plans (8-10) - Marshall Space Flight Center, Saturn V Dynamic Test Facility, East Test Area, Huntsville, Madison County, AL"
              - option "Floor Plans - Haddam Neck Nuclear Power Plant, Switchgear Building, 362 Injun Hollow Road, Haddam, Middlesex County, CT"
              - option "Fountain Details - Henry Overholser Mansion, 405 15th Street, Northwest, Oklahoma City, Oklahoma County, OK"
              - option "Front Elevation and Base Plan - Tannehill Furnace, 12632 Confederate Parkway, Tannehill Historical State Park, Bucksville, Tuscaloosa County, AL"
              - option "Ground Catchment Spillway and Pump Station Details - Hawaii Volcanoes National Park Water Collection System, Hawaii Volcanoes National Park, Volcano, Hawaii County, HI"
              - option "HABS CONN,1-NOWA,1- (sheet 13 of 13) - Taylor Sherman House, 89 Main Street, Norwalk, Fairfield County, CT"
              - option "HABS DEL,2-McDO.V,1-C- (sheet 2 of 3) - Monterey, Smokehouse, State Road 423, .7 mile East of Route 13, McDonough, New Castle County, DE"
              - option "HABS FLA,45-FERB,1- (sheet 1 of 6) - Old Fernandina Depot, 100 Atlantic Avenue, Fernandina Beach, Nassau County, FL"
              - option "HABS MONT,12-ANAC,1-U-; (sheet 2 of 2) - Anaconda Historic District, Ancient Order of Hibernians Hall, 321-323 East Commercial Street, Anaconda, Deer Lodge County, MT"
              - option "HABS OHIO,79-ZOAR,10- (sheet 2 of 4) - Grist Mill, First Street, Zoar, Tuscarawas County, OH"
              - option "HABS OKLA,42-GUTH,1G- (sheet 7 of 10) - State Capitol Company Building, 301 West Harrison Avenue, Guthrie, Logan County, OK"
              - option "HABS VI,1-CHRIS,2- (sheet 4 of 11) - Scalemshouse, Christiansted Wharf Square vicinity, Christiansted, St. Croix, VI"
              - option "HAER COLO,62-NERAY.V,1- (sheet 4 of 4) - Minuteman III ICBM Launch Control Facility November-1, 1.5 miles North of New Raymer and State Highway 14, New Raymer, Weld County, CO"
              - option "HAER NC,32-DURM,3- (sheet 2 of 2) - Liggett and Myers Tobacco Company, Watts Tobacco Warehouse, Gregson and West Peabody Streets, Durham, Durham County, NC"
              - option "HAER NC,41-GREBO,4- (sheet 1 of 3) - Pomona Terra Cotta Manufacturing Company, West Market Street, Greensboro, Guilford County, NC"
              - option "HAER NE-10-M (sheet 1 of 1) - South Omaha Union Stock Yards, Hog Shed (North), 2900 \"O\" Plaza, Omaha, Douglas County, NE"
              - option "HAER WASH,17-SEAT,14- (sheet 1 of 3) - Montlake Bridge, Spanning Montlake Cut at State Route 513, Seattle, King County, WA"
              - option "HAER WIS,34-ACK,1- (sheet 1 of 2) - Range Line Road Bridge, Spanning West Branch of Eau Claire River, on Range Line Road, Antigo, Langlade County, WI"
              - option "Head House and Residence, North Elevation - Creque Marine Railway, Charlotte Amalie, St. Thomas, VI"
              - option "Huff Area and Bungalows Site Plan - Camp Curry, Curry Village, Mariposa County, CA"
              - option "Lines - Gil Smith R Sloop PAULINE, Long Island Maritime Museum, West Sayville, Suffolk County, NY"
              - option "Longitudinal and Transverse Concrete Elevator Sections - Continental Grain Company, 307 South Washington Street, Brownwood, Brown County, TX"
              - option "Longitudinal Section B Levels 3, 4, and 5 - Montezuma Castle, Off I-17, Camp Verde, Yavapai County, AZ"
              - option "Lower Chord Detail - Ward's Crossing Bridge, Spanning Fourche Lafave River at Sunlight Bay Road (CR 8), Plainview, Yell County, AR"
              - option "Machinery, North Elevation - Creque Marine Railway, Charlotte Amalie, St. Thomas, VI"
              - option "Mill Office- Floor Plan - Ground Level - Shenandoah-Dives Mill, Mill Office, 135 County Road 2, Silverton, San Juan County, CO"
              - option "Northwest elevation and Southeast elevation - Kingston-Upon-Hill, Kitts Hummock Road, Dover, Kent County, DE"
              - option "Pine Valley - Section A-A - Pine Valley, Littlefield, Mohave County, AZ"
              - option "Pine Valley - Section B-B - Pine Valley, Littlefield, Mohave County, AZ"
              - option "Plan and Elevations - 25 Middle Street (House), 25 Middle Street, Valley, Chambers County, AL"
              - option "Plan - San Jacinto Ranch, Manager's House, San Jacinto, Elko County, NV"
              - option "Plans, Elevations - Eli Whitney Armory, Boarding House, Whitney Avenue, Hamden, New Haven County, CT"
              - option "Post Configuration East Elevation - Whittier Bridge, Spanning the Bearcamp River, West Ossipee, Carroll County, NH"
              - option "Ross Drive Bridge Details - Ross Drive Bridge, Spanning Rock Creek at Ross Drive, South of Joyce Road, NW, Washington, District of Columbia, DC"
              - option "SECOND STREET BRIDGE STRUCTURAL DETAILS - Second Street Bridge, Spanning former RFandP right-of-way, Richmond, Independent City, VA"
              - option "Section A-A, North End - Pine Brook Bridge, Spanning Pine Brook on Town Highway 3, Fayston, Washington County, VT"
              - option "Section B-B - Ben Thresher's Mill, State Aid No. 1, Barnet, Caledonia County, VT"
              - option "Section- Engine Room Aft, Pump Room Aft - Mission Santa Ynez, Suisun Bay Reserve Fleet, Benicia, Solano County, CA"
              - option "Section - J A Ranch Headquarters, Main House, Paloduro, Armstrong County, TX"
              - option "Shanley Camp - Sections - Shanley Camp, Littlefield, Mohave County, AZ"
              - option "Site Plan - Birmingham Industrial District, Birmingham, Jefferson County, AL"
              - option "site plan - Cedar Pass Lodge, 20681 South Dakota Highway 240, Interior, Jackson County, SD"
              - option "Site Plan - La Cienega Acequia, Truchas Molino, 334 Los Pinos Road, Santa Fe, Santa Fe County, NM"
              - option "Site plan - Rancho Grande, Elko, Elko County, NV"
              - option "SITE PLAN - Storer College, Anthony Hall, Camp Hill, Harpers Ferry, Jefferson County, WV"
              - option "Site Plan - Veterans Lake Dam, Veterans Lake Access Road, Sulphur, Murray County, OK"
              - option "Sixteenth Street Bridge Construction Details - Sixteenth Street Bridge, Spanning Piney Branch Parkway, Washington, District of Columbia, DC"
              - option "South Elevation, Deck Plan - Cornish-Windsor Covered Bridge, Spanning Connecticut River between Cornish, NH, and Windsor, VT, Cornish City, Sullivan County, NH"
              - option "South, North, West and East Elevations - Montana-Dakota Utilities Building, 2603 2nd Avenue North, Billings, Yellowstone County, MT"
              - option "Spencer Camp - Sections - Spencer Camp, Littlefield, Mohave County, AZ"
              - option "Spent Resin Storage Facility, Plans and Details - Haddam Neck Nuclear Power Plant, Spent Resin Storage Facility, 362 Injun Hollow Road, Haddam, Middlesex County, CT"
              - option "Statement of Significance and Site Plan - Margarita Martinez Homestead, Lindrith, Rio Arriba County, NM"
              - option "West Elevation and Plan - Judsonia Bridge, Spanning LIttle White River at County Road 66, Judsonia, White County, AR"
              - option "window and door details - Cedar Pass Lodge, Cabin 1-2, 20681 South Dakota Highway 240, Interior, Jackson County, SD"
              - option "window jamb details - Cedar Pass Lodge, Cabin 14-16, 20681 South Dakota Highway 240, Interior, Jackson County, SD"
              - option "AC20"
              - option "DigitalHub (RWTH Aachen) - arc"
              - option "Duplex Apartment - arc"
              - option "Fantasy office building 3 - arc"
              - option "HITOS office building (Tromsø) - arc"
              - 'option "FZK-Haus (Simple Phantasy Building) - Grundriss: Dachgeschoss"'
              - option "Maleva tänav 18 korterelamu (Esplanades example model)"
              - 'option "Maleva tänav 18 korterelamu (Esplanades example model) - Korruse plaan: 4.korrus"'
              - option "Medical-Dental Clinic - plumbing"
              - option "Molio Demo-hus"
              - 'option "Molio Demo-hus - Plantegning: Kælder"'
              - option "ResBIM residential unit 388"
              - option "13"
              - option "1810 S Park"
              - option "1810 S Park-Sheet - A001 - SITE PLAN"
              - option "1810 S Park-Sheet - A003 - EXISTING SITE PLAN"
              - option "1810 S Park-Sheet - A103 - ROOF PLAN"
              - option "1810 S Park-Sheet - A301 - BUILDING SECTION"
              - option "20141014 - 3232 Aalseth Lane - Street Elevation"
              - option "20150113_Diagrammatic Site Plan"
              - option "20150218_site plan_2nd Phase"
              - option "20150323 - Xcel_Floor & Site Plan"
              - option "20150521 - XSC - foundation questions & comments"
              - option "20150625 - XSC - glazing"
              - option "20150720 - XSC - floor plan and door schedule"
              - option "20150922 - XSC - A-100.A - SITE PLAN"
              - option "20171222 - The Downtowner - Fence Details"
              - option "20180816 - 705 Cherokee Path"
              - option "20180919 - Springhaven Laundry Mat - review before permit"
              - option "20181009 - Cannery Residences"
              - option "20181108 - 1810 S Park St - drawings for pricing exercise"
              - option "20190116 - CTR - Wall Thickness - OD comments"
              - option "20190219 - 1750 Ox - 1st & 2nd Phase-Sheet - A80 - SITE PLAN"
              - option "2019-022- Aalseth Residence - Revised Framing"
              - option "20190527 - 3196 Aalseth Lane-Sheet - A202 - BULDING ELEVATION - WEST"
              - option "20190612 - Oakfire2-Sheet - A201 - BUILDING ELEVATIONS"
              - option "20191011 - 1810 S Park"
              - option "30 day waiver - Sara Eskrich - 13th District"
              - option "3196 Aalseth Lane-Sheet - A301 - BUILDING SECTION"
              - option "335 W Lakeside St-Sheet - A202 - Elevation - East"
              - option "A-101 - Elevations (1)"
              - option "A-101 - Elevations v2"
              - option "A-101 - Elevations v2"
              - option "A402 - EXTERIOR DETAILS"
              - option "A-402 - Wall Sections"
              - option "A477 - 2ND FLOOR 1BD UNITS"
              - option "A-602 - Section Details - Exterior Envelope"
              - option "A-603 - Section Details - Exterior Envelope"
              - option "A700 - SCHEDULES"
              - option "A-701 - Restrooms"
              - option "A-801 - Door and Finish Schedules & Wall Types"
              - option "base model with wrong placements and extrusions - FreeCAD export"
              - option "bearing_wall_schedule_rev01"
              - option "Code Information"
              - option "colored_shapes"
              - option "CTR - 1st Phase - Shell-Reflected Ceiling Plan - BACKGROUND - RCP - 3RD FLOOR"
              - option "CTR - elevator elevations"
              - option "Detail 1 - Revised"
              - option "detail_Yorik_FreeCAD_materials"
              - option "Dream Kitchens_20141110_Schultz Kitchen Options"
              - option "F__Documents_Dropbox_ASCONProjects_IPythonAnalyst_Drawing1 Model (1)"
              - option "Lake_Kegonsa-Sheet - A-502 - Perspectives"
              - option "Laundry Mat-Sheet - A650 - EXISTING EQUIPMENT"
              - option "layout 02-markups"
              - option "Neighbor re-grading Permssion"
              - option "Open Source Metal Building_Interior-Sheet - A-101 - FLOOR PLAN - WAREHOUSE"
              - option "P1-04 - DETAILS"
              - option "Perspectives"
              - option "Print crema cafe HL 03"
              - option "Restoration Text"
              - option "S101 - ENLARGED PLANS"
              - option "Sheet A600 - 3196 Aalseth Lane - Schedules"
              - option "Sheet - S-101 - SCHEDULES, BASE PLATE AND PIER DETAILS"
              - option "Sheet - S-300 - FOUNDATION DETAILS"
              - option "Site plan"
              - option "Sports Complex - 3D View - Fitness Room_1"
              - option "Sports Complex-Sheet - A-402 - Wall Sections"
              - option "stairs.blend"
              - option "stairs_head"
              - option "The Downtowner_ARCH_2D and Schedules - Sheet - A500 - ADA RESTROOM & SCHEDULES"
              - option "The Downtowner_ARCH_Exterior Details 2"
              - option "The Downtowner_ARCH - Sheet - A501 - SCHEDULES"
              - option "The Downtowner_ARCH - Sheet - S500 - FRAMING SCHEDULE"
              - option "The_Downtowner_PLMB_ZS - Sheet - P0-00 - PLUMBING SYMBOLS & ABBREVIATIONS"
              - option "The Downtowner - Sheet - S100 - STRUCTURE ONLY"
              - option "Wall Detail"
              - option "XCEL-Sheet - A-301 - Building Sections"
              - option "Xcel_Sports Complex-Sheet - A-100-A - Site Plan"
              - option "Xcel_Sports Complex-Sheet - A-100-A - Site Plan"
              - option "Xcel_Sports Complex-Sheet - A-302 - Building Sections"
              - option "Xcel_Sports Complex-Sheet - A-403 - Wall Sections"
              - option "XSC - A-801 - Door and Finish Schedules & Wall Types"
              - option "XSC-Sheet - A-101-B - Enlarged First Floor Plan (East)"
              - option "site1000_bldg2082_floor9385"
              - option "site1015_bldg2113_floor9557"
              - option "site1040_bldg2136_floor9659"
              - option "site1047_bldg2154_floor9740"
              - option "site1088_bldg2216_floor10132"
              - option "site1098_bldg2234_floor10334"
              - option "site1101_bldg2241_floor10275"
              - option "site1102_bldg2242_floor10281"
              - option "site1110_bldg2250_floor10322"
              - option "site11265_bldg17059_floor45087"
              - option "site1138_bldg2292_floor10584"
              - option "site11692_bldg18240_floor48820"
              - option "site11704_bldg18258_floor48967"
              - option "site11711_bldg18268_floor48991"
              - option "site11861_bldg18508_floor50415"
              - option "site120_bldg55_floor209"
              - option "site1213_bldg2383_floor48290"
              - option "site157_bldg323_floor1313"
              - option "site1689_bldg2841_floor13117"
              - option "site1869_bldg2903_floor13293"
              - option "site208_bldg397_floor1579"
              - option "site2146_bldg2990_floor13636"
              - option "site2150_bldg3001_floor13690"
              - option "site2152_bldg3002_floor13692"
              - option "site2292_bldg3379_floor15050"
              - option "site2293_bldg3380_floor15055"
              - option "site2294_bldg3383_floor15064"
              - option "site248_bldg456_floor1800"
              - option "site261_bldg473_floor1873"
              - option "site274_bldg500_floor1980"
              - option "site279_bldg514_floor2041"
              - option "site285_bldg527_floor51568"
              - option "site289_bldg536_floor2149"
              - option "site294_bldg554_floor2233"
              - option "site303_bldg598_floor2434"
              - option "site3238_bldg4922_floor22515"
              - option "site3259_bldg4943_floor22529"
              - option "site3377_bldg5220_floor23409"
              - option "site339_bldg710_floor3024"
              - option "site3421_bldg5295_floor23605"
              - option "site3434_bldg5310_floor23630"
              - option "site357_bldg769_floor4266"
              - option "site3764_bldg5789_floor24598"
              - option "site383_bldg846_floor3730"
              - option "site3863_bldg6018_floor25218"
              - option "site4038_bldg6362_floor26166"
              - option "site4085_bldg6548_floor26706"
              - option "site418_bldg1080_floor4724"
              - option "site421_bldg1097_floor4796"
              - option "site4237_bldg7396_floor29509"
              - option "site424_bldg1074_floor4711"
              - option "site4267_bldg7556_floor30516"
              - option "site52_bldg298_floor1183"
              - option "site604_bldg1319_floor5779"
              - option "site610_bldg1324_floor50793"
              - option "site629_bldg1355_floor5906"
              - option "site644_bldg1390_floor6077"
              - option "site65_bldg3_floor5"
              - option "site719_bldg1540_floor6678"
              - option "site799_bldg1747_floor18743"
              - option "site892_bldg1902_floor8415"
              - option "site897_bldg1970_floor8690"
              - option "site926_bldg1958_floor8576"
              - option "site936_bldg1976_floor8706"
              - option "site980_bldg2055_floor9178"
              - option "changes-1794629194039-generated-for-demo"
              - option "changes-1794629346281-generated-for-demo"
              - option "changes-1794629601653-generated-for-demo"
              - option "changes-1794630313674-generated-for-demo"
              - option "changes-1794630874633-generated-for-demo"
              - option "stress-corrupt"
              - option "stress-corrupt"
              - option "stress-stress-r1-22959557"
              - option "stress-stress-r1-22959557"
              - option "stress-stress-r1-7156155"
              - option "stress-stress-r1-7156155"
              - option "stress-stress-r1-colorful-11960"
              - option "stress-stress-r1-colorful-11960"
              - option "stress-stress-r1-resbim-388_model"
              - option "stress-stress-r1-resbim-388_model"
              - option "stress-stress-r1-Restoration Text"
              - option "stress-stress-r1-Restoration Text"
              - option "stress-stress-r1-Site plan"
              - option "stress-stress-r1-Site plan"
              - option "upload-fixture-1794621617202"
              - option "upload-fixture-1794623338036"
              - option "upload-fixture-1794623391094"
              - option "upload-fixture-1794624315758"
              - option "upload-fixture-1794625085224"
              - option "upload-fixture-1794626229053"
              - option "upload-fixture-1794626785640"
              - option "upload-fixture-1794627355025"
              - option "upload-fixture-1794627956521"
              - option "upload-fixture-1794628199017"
              - option "upload-fixture-1794628449814"
              - option "upload-fixture-1794629199506"
              - option "upload-fixture-1794629371880"
              - option "upload-fixture-1794629610319"
              - option "upload-fixture-1794630321771"
              - option "upload-fixture-1794630882786"
              - option "upload_test"
              - option "upload_test"
              - option "upload_test"
              - option "00 Plànol Museu de Cultures del Món"
              - option "113. Glasgow Corporation Tramways - Plan of Power Station"
              - option "14 Garncarska Street, Kraków (02)"
              - option "150 MTM. Viipurin linnoitukset. Viipurin linna. Vankilan pohja-, profiili- ja fasadipiirustukset. Kolmannen kerroksen rakentamissuunnitelma. 1824"
              - option "270 of 'Black's Guide to Italy, according to the most recent railway routes, etc' (11056778015)"
              - option "307 of 'Rambles and Studies in Bosnia-Herzegovina and Dalmatia. With an account of the proceedings of the Congress of Archæologists and Anthropologists held in Sarajevo, August 1894. (With illustrations.)' (11302960553)"
              - option "9 Versailles 1750 De interne verbouwingen van Lodewijk XV en de gevel van Gabriel"
              - option "A collection of designs in architecture, containing new plans and elevations of houses, for general use Fleuron T101999-17"
              - option "ÅL STAVKIRKE - an10071112050092"
              - option "Amphiprostyle (PSF)"
              - option "Ansicht und Grundriss einer Villa"
              - option "Asuinkerrostalo EOL, Luotsikatu 5, pohjapiirustus 1901"
              - option "Atrium corinthicum"
              - option "Aufriss, Vorderansicht und Grundriss einer Villa"
              - option "Ausschnitt Karolingischer Klosterplan von St. Gallen Necessarien im Gästebereich"
              - option "Ausschnitt Karolingischer Klosterplan von St. Gallen Necessarien im Krankenbereich"
              - option "Bela Lajta tender site plan - National Theatre (Budapest)"
              - option "Bellapais-en"
              - option "Bengtskär Lighthouse drawing 2 fl., attic"
              - option "Boruy Fortress plan"
              - option "BuczaczSchematZamku"
              - option "Buttevant Friary Groundplan by Richard R. Brash 1852"
              - option "Byggnadsritning"
              - option "CASA DO CABIDO ALZADO PRINCIPAL"
              - option "Church of Saints Peter and Paul, Veliko Tarnovo plan"
              - option "Clausen's mansion, plan of ground floor"
              - option "Draft 1842"
              - option "Elevation of the baths and laundry at St. James's, Westminst"
              - option "En omgeving, situatietekening. - 's-Gravenhage - 20085286 - RCE"
              - option "Evolusie van motte noar stad"
              - option "Fig 004 Grundriss des Hauptgeschoßes in teilweiser Wiederherstellung"
              - option "Flehingen Neue Synagoge 42"
              - option "Fleming-Hof - Lageplan"
              - option "Floor plan for Springfield Union Station, 1888"
              - option "Freedom monument Latvia plan"
              - option "Ground-plan of the rooms in the Vatican Palace fitted up for library-purposes by Sixtus IV"
              - option "Grundbyggnad"
              - option "Grundriss Schloss Clerf"
              - option "Grundriss und Vorderansicht einer Villa"
              - option "Grunntegning av bygning på Kaglut Grønland"
              - option "Hereford Cathedral - steel engraved plan by B. Winkles after a drawing by Benjamin Baud, 1836"
              - option "Hôtel, rue Jean Tison Façade, Tourelle et détails Pl. I, Paris Musées 20230619090446"
              - option "I qvattro libri dell'architettvra"
              - option "Item from the Engetrim archive, ref. obj-0002096"
              - option "Jakob Ragaz Hotel Saratz Erweiterung Grundriss"
              - option "Jivno - půdorys (Král, 1891)"
              - option "Joy in Sorrow floorplan, G&P 1832"
              - option "Kantara Grundriss"
              - option "Kassel, Marie v. Boschan-Aschrott Altenheim, 1932 (Plan 2)"
              - option "Kibővített királyi palota földszinti alaprajza"
              - option "Kirche St. Peter Bapisterium Befunde 1958"
              - option "Kosciol Sw Szymona i Sw Heleny Minsk plan 1905 7"
              - option "Kostel sv.Martina - půdorys mine"
              - option "Kremsier Werkstättengebäude Hochparterre"
              - option "Lageplan Schloss Lontzen"
              - option "Lageplan Schloss Xhos"
              - option "Lageplan Skibo Castle"
              - option "L’Architecture de la Renaissance - Fig. 23"
              - option "L-Holzkirche"
              - option "Limassol Castle, ground plan 1918"
              - option "Maison Frison Plan d'extension déposé le 17 octobre 1924 élévation"
              - option "Myyrmäki Church compositional analysis"
              - option "MZK 001 Nr 11 Die St. Gertrudskirche zu Klosterneuburg - Tafel Fig. c Choransicht Innenraum"
              - option "NEMETHY(1876) p253 Mátyás templom Alaprajz"
              - option "Norra Grästorp Situationsplan"
              - option "Notre-Dame-des-Victoires de Paris Plan"
              - option "Nykøbing Kirke Mors destroyed 1890 plan"
              - option "Ontwerptekening - Middelburg - 20154544 - RCE"
              - option "Opole Norbert church plan 1938"
              - option "Ospiciul Central de Alienați lângă Bucuresci – Pavilionul Administrației – Fațada Principală"
              - option "Palopirtintie 6. Arkkitehti Paavo Perkkiö Helsingin kaupunkisuunnitteluvirastosta esittelemässä Itäkeskusta koskevia suunnittelmia Marjaniemen VPK:n Palopirtissä."
              - option "Parcazi Übersicht"
              - option "Photo framing-building example 2"
              - option "Planimetria del castello di Bodiam"
              - option "Planimetria generale dei corpi di fabbrica di Palazzo Litta e Palazzo della Società per le Strade Ferrate del Mediterraneo"
              - option "Plan of Mangana"
              - option "Plan st helena malta 001"
              - option "Planta Alta del Edificio del CETED"
              - option "Planta de projecto não realizado para a entrada da Rua Augusta (17 Agosto 1759) - Dionísio de S. Dionísio"
              - option "Planul bisericii fortificate de la Sura Mare"
              - option "Pl.grond, gevel nr. L 807 - Unknown - 20498413 - RCE"
              - option "Pôdorys bývalého premonštrátskeho kostola - Bíňa"
              - option "Pôdorys kostola sv. Antona Paduanskeho"
              - option "Podorys mileticova12"
              - option "Połacak, Spas. Полацак, Спас (1903) (2)"
              - option "Pongractelep lakas alaprajz 1940-es evek"
              - option "Porche.Vezelay.2"
              - option "Porolissum - Principia - Plan"
              - option "Prostylos"
              - option "Prostylos version 2"
              - option "Půdorys, Dominikánský klášter (Olomouc)"
              - option "Rannersdorf Grundriss LBK Sauer und Schwarzäugl 2006, 19"
              - option "Rathausplan von Ljubljana"
              - option "Rochdale site plan"
              - option "Rusgertorg Golosov 02"
              - option "Sádek, situační plán, okolo 1710"
              - option "Saint Joseph Church (Port Huron, Michigan) - Donaldson and Meier east elevation plan"
              - option "SanFlorianoVrPianta"
              - option "Schloss Raesfeld Lageplan 1729"
              - option "Schloss Schrattenthal Lageplan"
              - option "Seestadt Aspern, Vienna 20"
              - option "Simsongarður, Tungudal. Uppdráttur"
              - option "Sjønstå situasjonsplan 1942"
              - option "Stedje grunnplan"
              - option "St.John's church Ventspils"
              - option "St Matthew Chapel Qrendi Plan"
              - option "St Matthew Church Qrendi Plan"
              - option "St. Raphael (Berlin-Gatow) Grundriss"
              - option "Suggestions on the Arrangement and Characteristics of Parish Churches Figure 01 BL Scan"
              - option "Sv. Sava osnova"
              - option "Synagoge Arnsberg Lageplan"
              - option "Synagogue in Hvizdets plan"
              - option "Tatavár alaprajz1600"
              - option "TEKENING BOUWFRAGMENTEN (REPRODUCTIE) - Amsterdam - 20268056 - RCE"
              - option "Temples-of-Apollo-and-Athena Side Turkey"
              - option "Tlocrt moje kuce april 2013"
              - option "TomarChurchPlanCC3-pt"
              - option "Uncastillo (Zaragoza) San Juan 1 Planta"
              - option "Varagavank plan Bachmann 1913"
              - option "Viljandi Castle plan"
              - option "Wisig Quintañilla de las Vigñas plan new"
              - option "Wohnhaus Schlossstrasse 70 und 72, Stuttgart, Architekten Schmid & Burkhardt, Stuttgart, Tafel 76, Kick Jahrgang II, Grundriss"
              - option "Вялікі сабор у Бельчыцах"
              - option "Железнодорожный вокзал в Ревеле"
              - option "Храм-пахавальня полацкіх епіскапаў"
          - generic [ref=e78]:
            - text: Schedule
            - combobox "Schedule" [ref=e79]:
              - option "Every hour"
              - option "Every day" [selected]
              - option "Every week"
        - paragraph [ref=e80]: Repeats from creation or the last run. Next run times are shown in your local timezone.
        - button "Save automation" [ref=e81] [cursor=pointer]
      - paragraph [ref=e82]: No automations saved yet.
```

# Test source

```ts
  1  | import { expect, test } from '@playwright/test'
  2  | import type { Answer } from '../src/lib/types'
  3  | import type { Automation, Skill } from '../src/lib/skills'
  4  | 
  5  | const docId = 'ifc_bench__ac20-arc'
  6  | const question = 'How many windows are there?'
  7  | 
  8  | test('create a real skill, run it on AC20, and pick its prompt in the composer', async ({ page, request }) => {
  9  |   test.setTimeout(60_000)
  10 |   let skillId = ''
  11 |   const name = `AC20 windows ${Date.now()}`
  12 |   try {
  13 |     await page.goto('/#/skills')
  14 |     const screen = page.getByRole('region', { name: 'Skills', exact: true })
  15 |     await expect(screen.getByText('Starter', { exact: true })).toHaveCount(4)
  16 |     const create = screen.getByRole('form', { name: 'Create skill' })
  17 |     await create.getByLabel('Skill name', { exact: true }).fill(name)
  18 |     await create.getByLabel('Skill prompt', { exact: true }).fill(question)
  19 |     const saved = page.waitForResponse((response) => response.url().endsWith('/api/skills') && response.request().method() === 'POST')
  20 |     await create.getByRole('button', { name: 'Save skill', exact: true }).click()
  21 |     const created = await saved
  22 |     expect(created.status()).toBe(201)
  23 |     skillId = (await created.json() as Skill).id
  24 |     await screen.getByLabel('Run on drawing', { exact: true }).selectOption(docId)
  25 |     const card = screen.locator(`[data-skill-id="${skillId}"]`)
  26 |     await expect(card).toContainText(question)
  27 |     const running = page.waitForResponse((response) => response.url().endsWith(`/api/skills/${skillId}/run`))
  28 |     await card.getByRole('button', { name: 'Run skill', exact: true }).click()
  29 |     const result = await running
  30 |     expect(result.ok()).toBe(true)
  31 |     const { answer } = await result.json() as { answer: Answer }
  32 |     expect(answer.answer.abstained).toBe(false)
  33 |     expect(answer.doc_ids).toContain(docId)
  34 |     await expect(screen.getByRole('region', { name: 'Skill answer' })).toContainText(String(answer.answer.value))
  35 |     await page.goto('/#/chat')
  36 |     const picker = page.getByRole('combobox', { name: 'Use a skill' })
  37 |     await expect(picker).toBeEnabled()
  38 |     await picker.selectOption(skillId)
  39 |     await expect(page.getByRole('combobox', { name: 'Ask about your drawings' })).toHaveValue(question)
  40 |   } finally { if (skillId) expect((await request.delete(`/api/skills/${skillId}`)).status()).toBe(204) }
  41 | })
  42 | 
  43 | test('create a real automation, run it on AC20, and display and export its persisted report', async ({ page, request }) => {
  44 |   test.setTimeout(60_000)
  45 |   let automationId = ''
  46 |   const name = `AC20 daily ${Date.now()}`
  47 |   try {
  48 |     await page.goto('/#/automations')
  49 |     const screen = page.getByRole('region', { name: 'Automations', exact: true })
  50 |     const create = screen.getByRole('form', { name: 'Create automation' })
  51 |     await create.getByLabel('Automation name', { exact: true }).fill(name)
  52 |     await create.getByLabel('Automation prompt', { exact: true }).fill(question)
> 53 |     await create.getByLabel('Automation drawing', { exact: true }).selectOption(docId)
     |                                                                    ^ Error: locator.selectOption: Test timeout of 60000ms exceeded.
  54 |     await create.getByLabel('Schedule', { exact: true }).selectOption('1440')
  55 |     const saved = page.waitForResponse((response) => response.url().endsWith('/api/automations') && response.request().method() === 'POST')
  56 |     await create.getByRole('button', { name: 'Save automation', exact: true }).click()
  57 |     const created = await saved
  58 |     expect(created.status()).toBe(201)
  59 |     automationId = (await created.json() as Automation).id
  60 |     const card = screen.locator(`[data-automation-id="${automationId}"]`)
  61 |     await expect(card).toContainText('Not run yet')
  62 |     const running = page.waitForResponse((response) => response.url().endsWith(`/api/automations/${automationId}/run`))
  63 |     await card.getByRole('button', { name: 'Run now', exact: true }).click()
  64 |     const response = await running
  65 |     expect(response.ok()).toBe(true)
  66 |     const result = await response.json() as Automation
  67 |     expect(result.last_report?.ok).toBe(true)
  68 |     const answer = result.last_report!.answer!
  69 |     expect(answer.answer.abstained).toBe(false)
  70 |     const report = screen.getByRole('region', { name: 'Last automation report' })
  71 |     await expect(report.getByRole('heading', { name, exact: true })).toBeVisible()
  72 |     await expect(report).toContainText(String(answer.answer.value))
  73 |     await expect(card).not.toContainText('Not run yet')
  74 |     const downloadPromise = page.waitForEvent('download')
  75 |     await report.getByRole('button', { name: 'Export .md', exact: true }).click()
  76 |     const download = await downloadPromise
  77 |     expect(download.suggestedFilename()).toMatch(/\.md$/)
  78 |     const persisted = await request.get(`/api/automations/${automationId}/report.md`)
  79 |     expect(persisted.ok()).toBe(true)
  80 |     expect(await persisted.text()).toBe(result.last_report!.markdown)
  81 |   } finally { if (automationId) expect((await request.delete(`/api/automations/${automationId}`)).status()).toBe(204) }
  82 | })
  83 | 
```