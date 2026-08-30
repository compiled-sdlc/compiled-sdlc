package org.springframework.samples.petclinic.vets.web;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.WebMvcTest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.samples.petclinic.vets.model.Specialty;
import org.springframework.samples.petclinic.vets.model.Vet;
import org.springframework.samples.petclinic.vets.model.VetRepository;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.BDDMockito.given;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Acceptance check for CR-115: the list is answered conditionally, and its tag follows
 * the list rather than the request.
 *
 * Passability: Derive a tag from the list in the resource and compare it with the
 * request's If-None-Match. The fixture reads the tag off one response and replays it,
 * then changes the stubbed data to show the tag follows the list rather than the
 * request.
 * Confirmed empirically: 11 of 12 cells passed it in the full run.
 */
@WebMvcTest(VetResource.class)
@ActiveProfiles("test")
class VetListConditionalGetAcceptanceTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    VetRepository vetRepository;

    private Specialty aSpecialty(String name) {
        Specialty specialty = new Specialty();
        specialty.setName(name);
        return specialty;
    }

    private Vet aVet(int id, String firstName, String lastName, String... specialties) {
        Vet vet = new Vet();
        vet.setId(id);
        vet.setFirstName(firstName);
        vet.setLastName(lastName);
        for (String name : specialties) {
            vet.addSpecialty(aSpecialty(name));
        }
        return vet;
    }

    private String tagOfTheList() throws Exception {
        MvcResult result = mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andReturn();
        String tag = result.getResponse().getHeader(HttpHeaders.ETAG);
        assertThat(tag).as("the list carries an entity tag").isNotBlank();
        return tag;
    }

    @Test
    void shouldCarryAnEntityTag() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(aVet(1, "Helen", "Leary", "radiology")));

        tagOfTheList();
    }

    @Test
    void shouldAnswerNotModifiedToAMatchingTag() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(aVet(1, "Helen", "Leary", "radiology")));

        String tag = tagOfTheList();

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON).header(HttpHeaders.IF_NONE_MATCH, tag))
            .andExpect(status().isNotModified())
            .andExpect(result -> assertThat(result.getResponse().getContentAsString()).isEmpty());
    }

    @Test
    void shouldAnswerTheWholeListToATagThatDoesNotMatch() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(aVet(1, "Helen", "Leary", "radiology")));

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON)
                .header(HttpHeaders.IF_NONE_MATCH, "\"not-the-tag-of-this-list\""))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(1))
            .andExpect(jsonPath("$[0].lastName").value("Leary"));
    }

    @Test
    void shouldGiveTheSameTagForAnUnchangedListAndADifferentOneOnceItChanges() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(aVet(1, "Helen", "Leary", "radiology")));
        String before = tagOfTheList();
        assertThat(tagOfTheList()).as("an unchanged list keeps its tag").isEqualTo(before);

        given(vetRepository.findAll()).willReturn(List.of(
            aVet(1, "Helen", "Leary", "radiology"),
            aVet(2, "Rafael", "Ortega", "surgery")));
        assertThat(tagOfTheList()).as("a changed list gets a new tag").isNotEqualTo(before);

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON).header(HttpHeaders.IF_NONE_MATCH, before))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$.length()").value(2));
    }

    @Test
    void shouldKeepEveryFieldTheListAlreadyCarried() throws Exception {
        given(vetRepository.findAll()).willReturn(List.of(aVet(7, "Helen", "Leary", "radiology")));

        mvc.perform(get("/vets").accept(MediaType.APPLICATION_JSON))
            .andExpect(status().isOk())
            .andExpect(jsonPath("$[0].id").value(7))
            .andExpect(jsonPath("$[0].firstName").value("Helen"))
            .andExpect(jsonPath("$[0].lastName").value("Leary"))
            .andExpect(jsonPath("$[0].nrOfSpecialties").value(1))
            .andExpect(jsonPath("$[0].specialties[0].name").value("radiology"));
    }
}
